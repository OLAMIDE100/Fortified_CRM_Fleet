"""Google ADK CRM pipeline — Gemini agents over Postgres/pgvector (API-driven)."""

from __future__ import annotations

import logging
import os
import smtplib
import uuid
from email.message import EmailMessage
from typing import Any, Literal, Optional

from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent, LoopAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types
from typing_extensions import TypedDict

from helper_scripts.db import get_connection
from helper_scripts.otel_store import save_pipeline_telemetry
from helper_scripts.telemetry import (
    PipelineTelemetry,
    set_last_llm_usage,
    setup_telemetry,
    start_pipeline,
    traced_node,
)
from helper_scripts.vector_search import search_player_history
from nodes.crm_user_summary import USER_SUMMARY_INSTRUCTION, UserSummarySchema
from nodes.rag_transcript import (
    RAG_TRANSCRIPT_INSTRUCTION,
    RAGTranscriptAnalysisResult,
    _retrieve_rag_context,
)
from nodes.users_outreach import (
    CRITIC_INSTRUCTION,
    OUTREACH_INSTRUCTION,
    QUALIFY_INSTRUCTION,
    CriticSchema,
    OutreachSchema,
    QualificationSchema,
)

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv()
setup_telemetry()

logger = logging.getLogger(__name__)

ActionType = Literal["outreach", "update", "summarize"]

APP_NAME = "fortified_crm"
FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-3.5-flash")
PRO_MODEL = os.getenv("GEMINI_PRO_MODEL", "gemini-2.5-pro")
CRM_USER_ID = "crm_api"


def _ensure_gemini_credentials() -> None:
    """Prefer GEMINI_API_KEY; fall back to GOOGLE_API_KEY (GenAI SDK accepts either)."""
    gemini = (os.getenv("GEMINI_API_KEY") or "").strip()
    google = (os.getenv("GOOGLE_API_KEY") or "").strip()
    if gemini and not google:
        os.environ["GOOGLE_API_KEY"] = gemini
    elif google and not gemini:
        os.environ["GEMINI_API_KEY"] = google
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        raise RuntimeError(
            "Set GEMINI_API_KEY or GOOGLE_API_KEY for Gemini / google-adk"
        )


# Sync key aliases at import; hard failure deferred until an agent runs.
try:
    _ensure_gemini_credentials()
except RuntimeError:
    logger.warning(
        "GEMINI_API_KEY / GOOGLE_API_KEY not set yet; set before running CRM agents"
    )


class CRMState(TypedDict):
    action: str
    lead_id: str
    lead_name: str
    lead_email: str
    game_preference: str
    monthly_spend: float
    play_hours: float
    status: str
    existing_qualification_score: int
    existing_churn_risk_level: str
    qualification_score: int
    qualification_reasoning: str
    outreach_subject: Optional[str]
    outreach_body: Optional[str]
    critic_feedback: Optional[str]
    is_approved: bool
    revision_attempts: int
    email_sent: bool
    email_status: str
    human_approved: Optional[bool]
    awaiting_human_approval: bool
    sentiment: str
    churn_risk: str
    recurring_issues: str
    summary: str
    user_summary: str
    formatted_context: str


# ---------------------------------------------------------------------------
# Step A — ADK Agent initialization (Gemini)
# ---------------------------------------------------------------------------

search_player_history_tool = FunctionTool(search_player_history)

qualify_agent = Agent(
    name="qualify_lead_agent",
    model=FLASH_MODEL,
    instruction=QUALIFY_INSTRUCTION.strip(),
    output_schema=QualificationSchema,
    output_key="qualification",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

outreach_agent = Agent(
    name="outreach_agent",
    model=PRO_MODEL,
    instruction=OUTREACH_INSTRUCTION.strip(),
    output_schema=OutreachSchema,
    output_key="outreach",
    tools=[search_player_history_tool],
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

critic_agent = Agent(
    name="critic_evaluator_agent",
    model=FLASH_MODEL,
    instruction=CRITIC_INSTRUCTION.strip(),
    output_schema=CriticSchema,
    output_key="critic",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

rag_transcript_agent = Agent(
    name="rag_transcript_agent",
    model=FLASH_MODEL,
    instruction=RAG_TRANSCRIPT_INSTRUCTION.strip(),
    output_schema=RAGTranscriptAnalysisResult,
    output_key="rag_analysis",
    # RAG context is injected via formatted_context (pgvector tool used in Python).
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

summarize_user_agent = Agent(
    name="summarize_user_agent",
    model=FLASH_MODEL,
    instruction=USER_SUMMARY_INSTRUCTION.strip(),
    output_schema=UserSummarySchema,
    output_key="user_summary_parts",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

# ---------------------------------------------------------------------------
# Step B — Workflow hierarchy (SequentialAgent / LoopAgent)
# ---------------------------------------------------------------------------

outreach_revision_loop = LoopAgent(
    name="outreach_revision_loop",
    max_iterations=3,
    sub_agents=[outreach_agent, critic_agent],
)

outreach_workflow = SequentialAgent(
    name="outreach_workflow",
    sub_agents=[qualify_agent, outreach_revision_loop],
)

update_workflow = SequentialAgent(
    name="update_workflow",
    sub_agents=[rag_transcript_agent],
)

summarize_workflow = SequentialAgent(
    name="summarize_workflow",
    sub_agents=[summarize_user_agent],
)

# Session service enables HITL pause/resume across API calls.
_session_service = InMemorySessionService()
_hitl_checkpoints: dict[str, CRMState] = {}


def _parse_action(raw: str) -> ActionType:
    normalized = raw.strip().lower()
    aliases = {
        "1": "outreach",
        "outreach": "outreach",
        "generate outreach": "outreach",
        "2": "update",
        "update": "update",
        "update user": "update",
        "update users": "update",
        "3": "summarize",
        "summarize": "summarize",
        "summary": "summarize",
        "summarise": "summarize",
    }
    action = aliases.get(normalized)
    if action is None:
        raise ValueError(
            f"Unknown action '{raw}'. Choose: outreach | update | summarize"
        )
    return action


def empty_state(*, lead_id: str, action: ActionType) -> CRMState:
    return {
        "action": action,
        "lead_id": lead_id,
        "lead_name": "",
        "lead_email": "",
        "game_preference": "",
        "monthly_spend": 0.0,
        "play_hours": 0.0,
        "status": "",
        "existing_qualification_score": 0,
        "existing_churn_risk_level": "",
        "qualification_score": 0,
        "qualification_reasoning": "",
        "outreach_subject": None,
        "outreach_body": None,
        "critic_feedback": None,
        "is_approved": False,
        "revision_attempts": 0,
        "email_sent": False,
        "email_status": "",
        "human_approved": None,
        "awaiting_human_approval": False,
        "sentiment": "",
        "churn_risk": "",
        "recurring_issues": "",
        "summary": "",
        "user_summary": "",
        "formatted_context": "",
    }


def _run_adk_agent(agent: Agent, state: dict[str, Any], message: str) -> dict[str, Any]:
    """Invoke a single ADK agent; merge session state and capture Gemini usage."""
    _ensure_gemini_credentials()
    session_id = f"step-{uuid.uuid4().hex}"
    seed = {k: v for k, v in state.items() if v is not None}
    _session_service.create_session_sync(
        app_name=APP_NAME,
        user_id=CRM_USER_ID,
        session_id=session_id,
        state=seed,
    )
    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=_session_service,
    )

    input_tokens = 0
    output_tokens = 0
    model_name = str(getattr(agent, "model", None) or FLASH_MODEL)

    for event in runner.run(
        user_id=CRM_USER_ID,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=message)],
        ),
    ):
        usage = getattr(event, "usage_metadata", None)
        if usage is not None:
            input_tokens += int(getattr(usage, "prompt_token_count", None) or 0)
            output_tokens += int(getattr(usage, "candidates_token_count", None) or 0)

    set_last_llm_usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model_name,
    )

    session = _session_service.get_session_sync(
        app_name=APP_NAME,
        user_id=CRM_USER_ID,
        session_id=session_id,
    )
    return dict(session.state) if session else dict(state)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


@traced_node("load_lead", uses_llm=False)
def load_lead_node(state: CRMState) -> dict:
    """Fetch lead profile from Postgres by lead_id and initialize CRMState."""
    lead_id = state["lead_id"]
    print(f"\n[Node: Load Lead] Fetching profile for {lead_id}...")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, email, game_genre_preference, monthly_spend, play_time_hours_wk,
               status, qualification_score, churn_risk_level
        FROM leads
        WHERE id = %s
        """,
        (lead_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        raise ValueError(f"Lead '{lead_id}' not found in Postgres CRM database")

    (
        lead_id,
        name,
        email,
        genre,
        monthly_spend,
        play_hours,
        status,
        qualification_score,
        churn_risk_level,
    ) = row

    print(
        f" -> Loaded {name} <{email}> | Genre: {genre} | "
        f"Spend: ${monthly_spend}/mo | Hours: {play_hours}/wk | Status: {status}"
    )

    return {
        "lead_id": lead_id,
        "lead_name": name,
        "lead_email": email or "",
        "game_preference": genre or "",
        "monthly_spend": float(monthly_spend or 0),
        "play_hours": float(play_hours or 0),
        "status": status or "",
        "existing_qualification_score": int(qualification_score or 0),
        "existing_churn_risk_level": churn_risk_level or "Unknown",
        "qualification_score": 0,
        "qualification_reasoning": "",
        "outreach_subject": None,
        "outreach_body": None,
        "critic_feedback": None,
        "is_approved": False,
        "revision_attempts": 0,
        "email_sent": False,
        "email_status": "",
        "sentiment": "",
        "churn_risk": "",
        "recurring_issues": "",
        "summary": "",
        "user_summary": "",
        "formatted_context": "",
    }


@traced_node("qualify_lead", uses_llm=True)
def qualify_lead_node(state: CRMState) -> dict:
    print(f"\n[Node: Lead Qualifier] Processing {state['lead_name']}...")
    updated = _run_adk_agent(
        qualify_agent,
        state,
        f"Qualify lead {state['lead_name']} for premium outreach.",
    )
    parsed = QualificationSchema.model_validate(_as_dict(updated.get("qualification")))
    print(f" -> Score: {parsed.score}/100 | Reasoning: {parsed.reasoning}")
    return {
        "qualification_score": parsed.score,
        "qualification_reasoning": parsed.reasoning,
    }


@traced_node("generate_outreach", uses_llm=True)
def generate_outreach_node(state: CRMState) -> dict:
    attempt = state.get("revision_attempts", 0) + 1
    print(f"\n[Node: Outreach Generator] Drafting Email (Attempt #{attempt})...")
    seed = dict(state)
    seed["critic_feedback"] = state.get("critic_feedback") or "None (Initial Draft)"
    seed["qualification_reasoning"] = state.get("qualification_reasoning") or ""
    updated = _run_adk_agent(
        outreach_agent,
        seed,
        f"Draft outreach email attempt #{attempt} for {state['lead_name']}.",
    )
    parsed = OutreachSchema.model_validate(_as_dict(updated.get("outreach")))
    print(f" -> Generated Draft Subject: '{parsed.subject}'")
    return {
        "outreach_subject": parsed.subject,
        "outreach_body": parsed.body,
        "revision_attempts": attempt,
    }


@traced_node("critic_evaluator", uses_llm=True)
def critic_evaluator_node(state: CRMState) -> dict:
    print("\n[Node: Critic Evaluator] Auditing Draft Quality...")
    updated = _run_adk_agent(
        critic_agent,
        state,
        f"Review the outreach draft for {state['lead_name']}.",
    )
    parsed = CriticSchema.model_validate(_as_dict(updated.get("critic")))
    print(f" -> Approved: {parsed.is_approved}")
    print(f" -> Feedback: {parsed.feedback}")
    return {
        "is_approved": parsed.is_approved,
        "critic_feedback": parsed.feedback,
    }


@traced_node("send_outreach_email", uses_llm=False)
def send_outreach_email_node(state: CRMState) -> dict:
    """Send the critic-approved outreach email to the lead."""
    to_addr = state.get("lead_email") or ""
    subject = state.get("outreach_subject") or "(no subject)"
    body = state.get("outreach_body") or ""

    print(f"\n[Node: Send Outreach Email] To: {to_addr}")
    if not to_addr:
        print(" -> Skipped: lead has no email on file.")
        return {"email_sent": False, "email_status": "missing_recipient"}

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    from_addr = os.getenv("SMTP_FROM", smtp_user).strip()

    if not smtp_host or not from_addr:
        print(" -> SMTP not configured (set SMTP_HOST / SMTP_FROM). Simulating send:")
        print(f"    From: {from_addr or 'crm@localhost'}")
        print(f"    To:   {to_addr}")
        print(f"    Subj: {subject}")
        print(f"    Body: {body[:160]}{'...' if len(body) > 160 else ''}")
        return {"email_sent": True, "email_status": "simulated"}

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
        print(f" -> Email sent successfully to {to_addr}")
        return {"email_sent": True, "email_status": "sent"}
    except Exception as exc:
        print(f" -> Email send failed: {exc}")
        return {"email_sent": False, "email_status": f"error: {exc}"}


@traced_node("human_approval", uses_llm=False)
def human_approval_node(state: CRMState) -> dict:
    """Pause for a human to approve or reject the critic-approved draft."""
    print(
        f"\n[Node: Human Approval] Waiting for decision on {state['lead_id']}..."
    )
    # Decision is injected by resume_human_decision before this node re-runs.
    decision = state.get("human_approved")
    if decision is None:
        return {
            "awaiting_human_approval": True,
            "email_status": "awaiting_human_approval",
        }

    approved = bool(decision)
    print(f" -> Human decision: {'approve' if approved else 'reject'}")
    return {
        "human_approved": approved,
        "awaiting_human_approval": False,
        "email_status": "human_approved" if approved else "human_rejected",
    }


@traced_node("rag_transcript_analysis", uses_llm=True)
def rag_transcript_analysis_node(state: CRMState) -> dict:
    print("\n[Node: RAG Transcript Analyzer] Analyzing Player History...")
    formatted_context = _retrieve_rag_context(state["lead_id"])
    seed = dict(state)
    seed["formatted_context"] = formatted_context
    updated = _run_adk_agent(
        rag_transcript_agent,
        seed,
        f"Analyze RAG transcript history for {state['lead_name']}.",
    )
    parsed = RAGTranscriptAnalysisResult.model_validate(
        _as_dict(updated.get("rag_analysis"))
    )
    print(f" -> Sentiment: {parsed.sentiment}")
    print(f" -> Churn Risk: {parsed.churn_risk}")
    print(f" -> Recurring Issues: {', '.join(parsed.recurring_issues)}")
    print(f" -> Summary: {parsed.summary}")
    return {
        "sentiment": parsed.sentiment,
        "churn_risk": parsed.churn_risk,
        "recurring_issues": ", ".join(parsed.recurring_issues),
        "summary": parsed.summary,
        "formatted_context": formatted_context,
    }


@traced_node("summarize_user", uses_llm=True)
def summarize_user_node(state: CRMState) -> dict:
    """Summarize player using DB profile + RAG chat history."""
    print(f"\n[Node: Summarize User] Building summary for {state['lead_name']}...")
    formatted_context = _retrieve_rag_context(state["lead_id"])
    seed = dict(state)
    seed["formatted_context"] = formatted_context
    updated = _run_adk_agent(
        summarize_user_agent,
        seed,
        f"Summarize CRM profile and history for {state['lead_name']}.",
    )
    parsed = UserSummarySchema.model_validate(
        _as_dict(updated.get("user_summary_parts"))
    )

    full_summary = (
        f"PROFILE OVERVIEW\n{parsed.profile_overview}\n\n"
        f"INTERACTION INSIGHTS\n{parsed.interaction_insights}\n\n"
        f"RISK & OPPORTUNITY\n{parsed.risk_and_opportunity}\n\n"
        f"RECOMMENDED NEXT STEPS\n"
        + "\n".join(f"- {step}" for step in parsed.recommended_next_steps)
        + f"\n\nEXECUTIVE SUMMARY\n{parsed.executive_summary}"
    )
    print("\n=== USER SUMMARY ===")
    print(full_summary)
    return {
        "user_summary": full_summary,
        "formatted_context": formatted_context,
    }


@traced_node("update_crm", uses_llm=False)
def update_crm_node(state: CRMState) -> dict:
    """Persist outreach and/or churn fields depending on which path ran."""
    print(f"\n[Node: CRM Database Update] Persisting records for {state['lead_id']}...")
    action = state.get("action", "")

    if action == "outreach":
        if state.get("human_approved") is False and state.get("is_approved"):
            status = "Human Rejected Outreach"
        elif state.get("is_approved") and state.get("email_sent"):
            status = "Qualified & Outreached"
        elif state.get("is_approved") and state.get("human_approved") is True:
            status = "Approved — Email Failed"
        elif state.get("is_approved"):
            status = "Awaiting Human Approval"
        elif state.get("outreach_body"):
            status = "Outreach Failed Audit"
        else:
            status = "Below Outreach Threshold"
        qualification_score = state.get("qualification_score") or state.get(
            "existing_qualification_score", 0
        )
        last_outreach = state.get("outreach_body")
        churn_risk = state.get("churn_risk") or state.get(
            "existing_churn_risk_level", "Unknown"
        )
    else:
        status = state.get("status") or "Updated"
        qualification_score = state.get("existing_qualification_score", 0)
        last_outreach = None
        churn_risk = state.get("churn_risk") or state.get(
            "existing_churn_risk_level", "Unknown"
        )

    conn = get_connection()
    cursor = conn.cursor()

    if action == "outreach":
        cursor.execute(
            """
            UPDATE leads
            SET qualification_score = %s, status = %s, last_outreach = %s
            WHERE id = %s
            """,
            (qualification_score, status, last_outreach, state["lead_id"]),
        )
    else:
        cursor.execute(
            """
            UPDATE leads
            SET churn_risk_level = %s, status = %s
            WHERE id = %s
            """,
            (churn_risk, f"Churn Assessed: {churn_risk}", state["lead_id"]),
        )

    conn.commit()
    conn.close()
    print(" -> Postgres CRM update complete.")
    return {}


def _merge(state: CRMState, delta: dict) -> CRMState:
    merged = dict(state)
    merged.update(delta)
    return merged  # type: ignore[return-value]


def _run_outreach_path(state: CRMState, *, thread_id: str) -> CRMState:
    """Qualify → (score≥50) draft↔critic loop → HITL → send? → CRM update."""
    state = _merge(state, qualify_lead_node(state))
    if state["qualification_score"] < 50:
        print(" -> Score below threshold. Skipping outreach generation.")
        return _merge(state, update_crm_node(state))

    # LoopAgent-equivalent revision cycle (max 3), driven by critic approval.
    while True:
        state = _merge(state, generate_outreach_node(state))
        state = _merge(state, critic_evaluator_node(state))
        if state["is_approved"]:
            break
        if state["revision_attempts"] >= 3:
            print(
                " ! Max revision threshold reached (3 attempts). "
                "Skipping send; updating CRM."
            )
            return _merge(state, update_crm_node(state))
        print(
            " -> Draft rejected by Critic. "
            "Routing back to Outreach Generator for revision..."
        )

    state = _merge(state, human_approval_node(state))
    if state.get("awaiting_human_approval"):
        _hitl_checkpoints[thread_id] = state
        return state

    if state.get("human_approved"):
        state = _merge(state, send_outreach_email_node(state))
    else:
        print(" -> Human rejected draft. Skipping send; updating CRM.")
    return _merge(state, update_crm_node(state))


def _run_update_path(state: CRMState) -> CRMState:
    state = _merge(state, rag_transcript_analysis_node(state))
    return _merge(state, update_crm_node(state))


def _run_summarize_path(state: CRMState) -> CRMState:
    return _merge(state, summarize_user_node(state))


def build_crm_workflow() -> SequentialAgent:
    """ADK workflow hierarchy used by the CRM platform (hackathon / docs surface)."""
    return SequentialAgent(
        name="crm_root_workflow",
        description="Routes are executed by run_crm_pipeline; agents defined above.",
        sub_agents=[outreach_workflow, update_workflow, summarize_workflow],
    )


def run_crm_pipeline(
    lead_id: str, action: str
) -> tuple[dict[str, Any], PipelineTelemetry]:
    """Run the ADK CRM pipeline; return final/paused state + OpenTelemetry metrics."""
    parsed_action = _parse_action(action)
    thread_id = f"{parsed_action}-{lead_id}-{uuid.uuid4().hex[:10]}"

    with start_pipeline(lead_id=lead_id, action=parsed_action) as finish:
        state = empty_state(lead_id=lead_id, action=parsed_action)
        state = _merge(state, load_lead_node(state))

        if parsed_action == "outreach":
            state = _run_outreach_path(state, thread_id=thread_id)
        elif parsed_action == "update":
            state = _run_update_path(state)
        else:
            state = _run_summarize_path(state)

        telemetry = finish()

    result = dict(state)
    result["thread_id"] = thread_id
    if result.get("awaiting_human_approval"):
        result["email_status"] = (
            result.get("email_status") or "awaiting_human_approval"
        )

    try:
        telemetry.run_id = save_pipeline_telemetry(telemetry)
    except Exception as exc:
        logger.exception("Failed to persist OpenTelemetry metrics: %s", exc)
    return result, telemetry


def resume_human_decision(
    thread_id: str, decision: Literal["approve", "reject"]
) -> tuple[dict[str, Any], PipelineTelemetry]:
    """Resume a paused outreach run after human approve/reject."""
    if thread_id not in _hitl_checkpoints:
        raise ValueError(f"Unknown approval thread_id '{thread_id}'")

    state = dict(_hitl_checkpoints[thread_id])
    if not state.get("awaiting_human_approval"):
        raise ValueError(f"Thread '{thread_id}' is not awaiting human approval")

    lead_id = str(state.get("lead_id") or "")
    action = str(state.get("action") or "outreach")
    approved = decision == "approve"

    with start_pipeline(lead_id=lead_id, action=f"{action}:human") as finish:
        state["human_approved"] = approved
        state["awaiting_human_approval"] = False
        state = _merge(state, human_approval_node(state))  # type: ignore[arg-type]

        if approved:
            state = _merge(state, send_outreach_email_node(state))  # type: ignore[arg-type]
        else:
            print(" -> Human rejected draft. Skipping send; updating CRM.")

        state = _merge(state, update_crm_node(state))  # type: ignore[arg-type]
        telemetry = finish()

    _hitl_checkpoints.pop(thread_id, None)

    result = dict(state)
    result["awaiting_human_approval"] = False
    result["thread_id"] = thread_id
    result["human_approved"] = approved

    try:
        telemetry.run_id = save_pipeline_telemetry(telemetry)
    except Exception as exc:
        logger.exception("Failed to persist OpenTelemetry metrics: %s", exc)
    return result, telemetry


def run_crm_pipeline_batch(
    lead_ids: list[str], action: str
) -> list[tuple[dict[str, Any], PipelineTelemetry]]:
    """Run the pipeline for each lead (outreach / update batch support)."""
    parsed_action = _parse_action(action)
    if parsed_action == "summarize" and len(lead_ids) != 1:
        raise ValueError("summarize requires exactly one lead_id")
    if not lead_ids:
        raise ValueError("At least one lead_id is required")

    seen: set[str] = set()
    ordered: list[str] = []
    for raw in lead_ids:
        lead_id = (raw or "").strip()
        if not lead_id or lead_id in seen:
            continue
        seen.add(lead_id)
        ordered.append(lead_id)

    if not ordered:
        raise ValueError("At least one lead_id is required")

    return [
        run_crm_pipeline(lead_id=lead_id, action=parsed_action) for lead_id in ordered
    ]
