## Inspiration

I work as a **data platform engineer** at an iGaming company. My days are pipelines, warehouses, and keeping player data trustworthy. The gap I kept noticing was not “more dashboards”—it was the **CRM motion** on top of that data.

We already know spend, play hours, genre preference, and often *why* someone opened a support ticket. Still, outreach starts from templates. Churn shows up late. VIP summaries get pasted together by hand. I wanted something that closes that loop the way a platform person thinks: **qualify → draft → critique → pause for a human → send → write back**, with the same Postgres/vector habits I trust in production.

The Google Hackathon was the excuse to build it properly—not a single chat box, but **FastAPI + React**, **Google ADK + Gemini**, **pgvector RAG**, **HITL**, **OpenTelemetry**, and a real path from **Docker Compose** to **GKE**. That became the **Agentic CRM Platform** (Fortified CRM Fleet).

---

## What it does

Three actions over one lead profile:

| Action | What happens |
|--------|----------------|
| **Outreach** | Score the player, draft a genre-aware email, run a critic loop, wait for Approve/Reject in the UI, then send (or simulate SMTP) and update CRM |
| **Update** | RAG over chat history → sentiment / churn / recurring issues → persist churn risk |
| **Summarize** | Profile + transcript context → actionable briefing (no CRM write) |

The UI filters leads, supports multi-select outreach/update, and surfaces **Approve & send** / **Reject** when a draft is waiting on a human.

Under the hood the rules stay explainable. Qualification is $s \in [0, 100]$; we only generate outreach when

$$
s \ge 50
$$

Critic revisions are bounded so agents cannot thrash forever:

$$
n_{\mathrm{rev}} \le 3
$$



---

## How we built it

1. **Data first.** Tables for `leads`, `transcript_logs`, `transcript_embeddings`, and `otel_*`. Seed jobs load players/logs and embed history—no empty vector index pretending to be smart.

2. **Thin API, sharp agents.** FastAPI exposes `/api/v1/crm/run` and `/api/v1/crm/human-decision`. Orchestration lives in `agentic_rag_crm.py` with Google ADK agents: Flash for qualify/critic/RAG/summary, Pro for outreach, plus `search_player_history` as an ADK tool.

3. **HITL on the critical path.** In iGaming a bad email is a brand/compliance issue. Critic can reject; humans still gate send.

4. **Two deploy stories.** Local Compose (UI `:8080`, backend, pgvector, seed profile). Production-shaped Terraform (VPC, GKE, Cloud SQL, Artifact Registry, WI) + Kubernetes manifests + `deploy.sh` / GitHub Actions aligned to the same apply order.

5. **Migration when the rules required it.** We started closer to a LangGraph/OpenAI sketch, then moved LLM calls to **ADK + Gemini 2.5** while keeping Postgres, FastAPI, and OTel.

---

## Challenges we ran into

- **Scope vs honesty.** Easy to add more agents; harder to ship three clear actions with one HITL gate.
- **Docker build context.** Backend image needs repo root (`backend/` + `helper_scripts/`). Building with context `../backend` from Terraform failed until we fixed `-f` + context like Compose.
- **GCP identity.** ADC scope crashes after a suspended login; wrong project/account → “no permission to access Project…”. Half of deploy is IAM hygiene.
- **CI ↔ `deploy.sh` drift.** Manifests, secrets, and Actions each wanted a different story. Aligning `merge.yml` to the same render (`:v1.0.0` → tag) and apply order removed a lot of “works locally” pain.
- **Critic-tight copy.** Genre mention, CTA, and word-count bounds rejected a lot of first drafts until instructions and feedback loops tightened.

---

## Accomplishments that we're proud of

- An end-to-end **agentic CRM** that writes back to the database—not just chat.
- **Human-in-the-loop** before send, with a critic loop capped at three revisions.
- **RAG over real-ish support history** (lag vs billing queries) grounded in pgvector.
- **Observability** (pipeline/node spans, tokens, cost) persisted for review even when the UI stays operational.
- A deploy path that looks like work I would show a platform team: Compose → Terraform → GKE Ingress, plus architecture diagrams and a seed Job.

---

## What we learned

- Agents are only as good as **retrieval + write-back**. Pretty drafts that never update `leads` are toys.
- **HITL changes architecture.** In-memory pause/resume is fine for a demo; multi-replica needs sticky sessions or a shared store.
- **Domain language beats model size.** iGaming fields and RAG seeds (“server lag…”, “refund billing…”) mattered more than swapping Flash for a larger model everywhere.
- Platform habits transfer: **change the agent runtime, keep the data plane**; treat CI like another environment, not a special case.
- Instrumentation ($t_{\mathrm{in}}$, $t_{\mathrm{out}}$, cost) is how you defend an agent system to risk and finance—not optional polish.

---

## What's next for Agentic CRM Platform

- Shared HITL store (Redis / DB) so pause/resume survives multiple backend pods.
- Cloud SQL Auth Proxy / private connectivity as the default prod DB path; tighten secrets via Secret Manager + External Secrets.
- Richer OTel in the UI (cost/latency per action) for CSMs and platform owners.
- More channels (in-app / push) with the same critic + HITL gate.
- Evaluation harness: golden leads, critic pass-rate, retrieval hit-rate—so we can improve agents without vibes-only demos.
- Closer coupling to warehouse signals (LTV bands, responsible-gaming flags) so qualification uses the same truth the rest of the iGaming data platform already trusts.
