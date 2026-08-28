"""FastAPI entrypoint for the Agentic CRM Platform."""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from agentic_rag_crm import resume_human_decision, run_crm_pipeline_batch
from helper_scripts.db import get_connection, get_database_url
from helper_scripts.otel_store import (
    get_pipeline_run,
    list_pipeline_runs,
)
from helper_scripts.telemetry import setup_telemetry

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agentic CRM Platform",
    description=(
        "Google ADK + Gemini CRM agents over Postgres + pgvector: "
        "outreach, churn update, and user summary."
    ),
    version="0.1.0",
)


@app.on_event("startup")
def _startup() -> None:
    setup_telemetry()



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CRMRunRequest(BaseModel):
    action: Literal["outreach", "update", "summarize"] = Field(
        ...,
        description="Pipeline to run",
    )
    lead_id: Optional[str] = Field(
        default=None,
        examples=["L101"],
        description="Single lead ID (required for summarize; optional if lead_ids set)",
    )
    lead_ids: Optional[list[str]] = Field(
        default=None,
        examples=[["L101", "L102"]],
        description="Multiple lead IDs (outreach / update only)",
    )

    @model_validator(mode="after")
    def validate_lead_selection(self) -> "CRMRunRequest":
        ids = self.resolved_lead_ids()
        if self.action == "summarize":
            if len(ids) != 1:
                raise ValueError("summarize requires exactly one lead_id")
        elif len(ids) < 1:
            raise ValueError("outreach/update require at least one lead_id or lead_ids")
        return self

    def resolved_lead_ids(self) -> list[str]:
        ids: list[str] = []
        if self.lead_ids:
            ids.extend(self.lead_ids)
        if self.lead_id:
            ids.append(self.lead_id)

        seen: set[str] = set()
        ordered: list[str] = []
        for raw in ids:
            lead_id = (raw or "").strip()
            if not lead_id or lead_id in seen:
                continue
            seen.add(lead_id)
            ordered.append(lead_id)
        return ordered


class NodeTelemetryOut(BaseModel):
    node: str
    duration_seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    uses_llm: bool = False


class PipelineTelemetryOut(BaseModel):
    run_id: Optional[int] = None
    lead_id: str
    action: str
    duration_seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    nodes: list[NodeTelemetryOut] = Field(default_factory=list)
    created_at: Optional[str] = None


class CRMRunResponse(BaseModel):
    action: str
    lead_id: str
    lead_name: str
    lead_email: str
    game_preference: str
    monthly_spend: float
    play_hours: float
    status: str
    qualification_score: int
    qualification_reasoning: str
    outreach_subject: Optional[str] = None
    outreach_body: Optional[str] = None
    critic_feedback: Optional[str] = None
    is_approved: bool
    revision_attempts: int
    email_sent: bool
    email_status: str
    human_approved: Optional[bool] = None
    awaiting_human_approval: bool = False
    thread_id: Optional[str] = None
    sentiment: str
    churn_risk: str
    recurring_issues: str
    summary: str
    user_summary: str


class CRMBatchRunResponse(BaseModel):
    action: str
    count: int
    results: list[CRMRunResponse]
    pending_approvals: int = 0


class HumanDecisionRequest(BaseModel):
    thread_id: str = Field(..., description="Thread id from a paused outreach run")
    decision: Literal["approve", "reject"] = Field(
        ...,
        description="Human decision before sending the outreach email",
    )


class LeadProfile(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    game_genre_preference: Optional[str] = None
    monthly_spend: Optional[float] = None
    play_time_hours_wk: Optional[float] = None
    status: Optional[str] = None
    qualification_score: Optional[int] = None
    churn_risk_level: Optional[str] = None
    last_outreach: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    database_url_host: str


def _row_to_lead(row) -> LeadProfile:
    return LeadProfile(
        id=row[0],
        name=row[1],
        email=row[2],
        game_genre_preference=row[3],
        monthly_spend=row[4],
        play_time_hours_wk=row[5],
        status=row[6],
        qualification_score=row[7],
        churn_risk_level=row[8],
        last_outreach=row[9],
    )


def _state_to_response(result: dict) -> CRMRunResponse:
    # Telemetry is persisted to Postgres and available via /api/v1/telemetry —
    # it is intentionally omitted from CRM run responses (UI-facing).
    payload = {k: result.get(k) for k in CRMRunResponse.model_fields}
    if payload.get("awaiting_human_approval") is None:
        payload["awaiting_human_approval"] = False
    return CRMRunResponse(**payload)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    url = get_database_url()
    host_hint = url.split("@")[-1] if "@" in url else url
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        return HealthResponse(status="ok", database_url_host=host_hint)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@app.get("/api/v1/lead-filters")
def lead_filter_options() -> dict[str, list[str]]:
    """Distinct values for genre / status / churn dropdowns."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
          ARRAY_AGG(DISTINCT game_genre_preference ORDER BY game_genre_preference)
            FILTER (WHERE game_genre_preference IS NOT NULL AND game_genre_preference <> ''),
          ARRAY_AGG(DISTINCT status ORDER BY status)
            FILTER (WHERE status IS NOT NULL AND status <> ''),
          ARRAY_AGG(DISTINCT churn_risk_level ORDER BY churn_risk_level)
            FILTER (WHERE churn_risk_level IS NOT NULL AND churn_risk_level <> '')
        FROM leads
        """
    )
    row = cur.fetchone()
    conn.close()
    genres, statuses, churn = row or (None, None, None)
    return {
        "game_genre_preference": list(genres or []),
        "status": list(statuses or []),
        "churn_risk_level": list(churn or []),
    }


@app.get("/api/v1/leads", response_model=list[LeadProfile])
def list_leads(
    limit: int = Query(default=100, ge=1, le=500),
    id: Optional[str] = Query(default=None, description="Partial lead id match"),
    email: Optional[str] = Query(default=None, description="Partial email match"),
    game_genre_preference: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    churn_risk_level: Optional[str] = Query(default=None),
) -> list[LeadProfile]:
    clauses: list[str] = []
    params: list[object] = []

    if id and id.strip():
        clauses.append("id ILIKE %s")
        params.append(f"%{id.strip()}%")
    if email and email.strip():
        clauses.append("email ILIKE %s")
        params.append(f"%{email.strip()}%")
    if game_genre_preference and game_genre_preference.strip():
        clauses.append("game_genre_preference = %s")
        params.append(game_genre_preference.strip())
    if status and status.strip():
        clauses.append("status = %s")
        params.append(status.strip())
    if churn_risk_level and churn_risk_level.strip():
        clauses.append("churn_risk_level = %s")
        params.append(churn_risk_level.strip())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT id, name, email, game_genre_preference, monthly_spend,
               play_time_hours_wk, status, qualification_score,
               churn_risk_level, last_outreach
        FROM leads
        {where}
        ORDER BY id
        LIMIT %s
        """,
        params,
    )
    rows = cur.fetchall()
    conn.close()
    return [_row_to_lead(row) for row in rows]


@app.get("/api/v1/leads/{lead_id}", response_model=LeadProfile)
def get_lead(lead_id: str) -> LeadProfile:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, email, game_genre_preference, monthly_spend,
               play_time_hours_wk, status, qualification_score,
               churn_risk_level, last_outreach
        FROM leads
        WHERE id = %s
        """,
        (lead_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Lead '{lead_id}' not found")
    return _row_to_lead(row)


@app.get("/api/v1/telemetry", response_model=list[PipelineTelemetryOut])
def list_telemetry(
    lead_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[PipelineTelemetryOut]:
    """List stored OpenTelemetry pipeline runs (newest first)."""
    try:
        rows = list_pipeline_runs(lead_id=lead_id, action=action, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return [
        PipelineTelemetryOut(
            run_id=row["id"],
            lead_id=row["lead_id"],
            action=row["action"],
            duration_seconds=row["duration_seconds"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            total_tokens=row["total_tokens"],
            cost_usd=row["cost_usd"],
            model=row["model"],
            created_at=row.get("created_at"),
            nodes=row.get("nodes") or [],
        )
        for row in rows
    ]


@app.get("/api/v1/telemetry/{run_id}", response_model=PipelineTelemetryOut)
def get_telemetry(run_id: int) -> PipelineTelemetryOut:
    """Fetch one stored OpenTelemetry pipeline run by id."""
    try:
        row = get_pipeline_run(run_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail=f"Telemetry run '{run_id}' not found")
    return PipelineTelemetryOut(
        run_id=row["id"],
        lead_id=row["lead_id"],
        action=row["action"],
        duration_seconds=row["duration_seconds"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        total_tokens=row["total_tokens"],
        cost_usd=row["cost_usd"],
        model=row["model"],
        created_at=row.get("created_at"),
        nodes=row.get("nodes") or [],
    )


@app.post("/api/v1/crm/run", response_model=CRMBatchRunResponse)
def run_crm(request: CRMRunRequest) -> CRMBatchRunResponse:
    """Run outreach | update | summarize. outreach/update accept multiple lead_ids."""
    lead_ids = request.resolved_lead_ids()
    try:
        runs = run_crm_pipeline_batch(lead_ids=lead_ids, action=request.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    results = [_state_to_response(state) for state, _telemetry in runs]
    pending = sum(1 for r in results if r.awaiting_human_approval)
    return CRMBatchRunResponse(
        action=request.action,
        count=len(results),
        results=results,
        pending_approvals=pending,
    )


@app.post("/api/v1/crm/human-decision", response_model=CRMRunResponse)
def human_decision(request: HumanDecisionRequest) -> CRMRunResponse:
    """Approve or reject a critic-approved outreach draft before send."""
    try:
        state, _telemetry = resume_human_decision(
            thread_id=request.thread_id.strip(),
            decision=request.decision,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _state_to_response(state)
