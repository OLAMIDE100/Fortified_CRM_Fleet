# Fortified CRM Fleet

<p align="center">
  <img src="docs/fortified_crm_fleet_logo.png" alt="Fortified CRM Fleet logo" width="220" />
</p>

Agentic CRM platform for gaming / casino leads. **Google ADK + Gemini** agents qualify players, draft human-approved outreach, assess churn from RAG transcript history, and produce player summaries — served by **FastAPI** and a **React** UI, backed by **Postgres + pgvector**.

| Action | Pipeline | Multi-lead | Writes CRM? |
|--------|----------|------------|-------------|
| **outreach** | Qualify → draft ↔ critic → **HITL approve/reject** → send → update | Yes | Yes |
| **update** | RAG transcript analysis → write churn risk | Yes | Yes |
| **summarize** | Profile + RAG briefing | No (one lead) | No |

---

## Architecture diagrams

### Full system architecture (combined)

<p align="center">
  <img src="docs/full_architecture.png" alt="Fortified CRM Fleet full architecture" width="100%" />
</p>

<p align="center"><em>Figure 0 — End-to-end view: UI & edge → GKE/ADK pipelines → Cloud SQL/pgvector → platform & deploy paths</em></p>

### 1. Functionality — CRM agent pipelines

<p align="center">
  <img src="docs/agentic_crm_functionality.png" alt="CRM functionality and agent pipelines" width="100%" />
</p>

<p align="center"><em>Figure 1 — UI actions map to three ADK-driven pipelines (outreach with HITL, churn update, summarize)</em></p>

**Request path (runtime)**

```
POST /api/v1/crm/run { action, lead_id | lead_ids }
  → load_lead_node
  → route by action
       ├─ outreach
       │     qualify_lead_agent (gemini-3.5-flash)
       │       → score < 50 → update_crm → END
       │       → score ≥ 50 → loop (max 3):
       │            outreach_agent (gemini-2.5-pro + RAG tool)
       │            critic_evaluator_agent (flash)
       │              → critic OK → human_approval (pause)
       │                   ├─ approve → send_outreach_email → update_crm
       │                   └─ reject  → update_crm
       ├─ update    → rag_transcript_agent → update_crm
       └─ summarize → summarize_user_agent → END

POST /api/v1/crm/human-decision { thread_id, decision }
  → resume_human_decision()
```

---

### 2. Cloud & Kubernetes resources

<p align="center">
  <img src="docs/cloud_kubernetes_architecture.png" alt="GCP and Kubernetes architecture" width="100%" />
</p>

<p align="center"><em>Figure 2 — Public edge → GKE VPC → Cloud SQL; platform strip (Artifact Registry, IAM, Logging)</em></p>

| Layer | Resources |
|-------|-----------|
| **Public edge** | Global IP `fortified-crm-fleet` · DNS `fortified-crm-fleet.wolfcore.app` · Managed Certificate · GKE Ingress + FrontendConfig (TLS 1.2) |
| **GKE** (`europe-west3`) | Cluster / node pool `fortified-crm-fleet` · Namespace `fortified-crm-fleet` · Frontend + Backend Deployments/Services · Seed **Job** · Workload Identity SA |
| **Data** | Cloud SQL Postgres 14 (private IP) · tables `leads`, `transcript_logs`, `transcript_embeddings`, `otel_*` |
| **Platform** | Artifact Registry `fortified-crm-fleet` · GCP SA + WI binding · Logging / Monitoring / Secret Manager accessor |

**Images**

```text
europe-west3-docker.pkg.dev/<project>/fortified-crm-fleet/fortified-crm-fleet-backend:<tag>
europe-west3-docker.pkg.dev/<project>/fortified-crm-fleet/fortified-crm-fleet-frontend:<tag>
europe-west3-docker.pkg.dev/<project>/fortified-crm-fleet/fortified-crm-fleet-seed:<tag>
```

---

### 3. Python functions coexistence

<p align="center">
  <img src="docs/python_functions_coexistence.png" alt="Python modules and function coexistence" width="100%" />
</p>

<p align="center"><em>Figure 3 — API → ADK orchestration → nodes/helpers → Postgres / seed jobs</em></p>

| Layer | Path | Role |
|-------|------|------|
| **API** | `backend/main.py` | FastAPI routes, CORS, lead filters, telemetry reads |
| **Orchestration** | `backend/agentic_rag_crm.py` | ADK Agents, `run_crm_pipeline`, HITL resume, SMTP send |
| **Schemas / prompts** | `backend/nodes/` | Pydantic schemas + Gemini instructions |
| **Helpers** | `helper_scripts/` | DB, pgvector RAG, OpenTelemetry spans + Postgres store |
| **Seed** | `data_ingestion/` | Leads, logs, OTel schema, embeddings |

---

### 4. Deployment strategies — local vs production

<p align="center">
  <img src="docs/deployment_strategies.png" alt="Local Docker Compose vs production GKE deployment" width="100%" />
</p>

<p align="center"><em>Figure 4 — Compose for local iteration; Terraform + manifests for GKE production</em></p>

---

## Features

**UI**

- Filters: ID / email (text), genre / status / churn (dropdowns)
- Outreach / update: multi-select + **Select all from filter**
- Critic-approved drafts show **Approve & send** / **Reject**

**Agents (Google ADK)**

| Agent | Model (default) | Role |
|-------|-----------------|------|
| `qualify_lead_agent` | `gemini-3.5-flash` | Score 0–100 |
| `outreach_agent` | `gemini-2.5-pro` | Draft email (+ optional RAG tool) |
| `critic_evaluator_agent` | `gemini-3.5-flash` | Approve / feedback (≤3 revisions) |
| `rag_transcript_agent` | `gemini-3.5-flash` | Sentiment, churn, issues |
| `summarize_user_agent` | `gemini-3.5-flash` | Executive player briefing |

**Observability**

- Spans: `crm.pipeline`, `crm.node.*` (duration, tokens, cost)
- Tables: `otel_pipeline_runs`, `otel_node_spans`
- API: `GET /api/v1/telemetry` (not rendered in the UI)

---

## Project layout

```text
docker-compose.yaml
deploy.sh
backend/
  main.py                 # FastAPI
  agentic_rag_crm.py      # ADK agents + pipeline + HITL
  nodes/                  # Schemas + instructions
  Dockerfile
helper_scripts/
  db.py                   # Postgres helpers
  vector_search.py        # pgvector RAG (+ ADK tool)
  telemetry.py            # OpenTelemetry wrappers
  otel_store.py           # Persist / query OTel runs
frontend/                 # Vite + React + Tailwind + nginx
data_ingestion/           # Seed scripts + seed Dockerfile
infrastructure/
  terraform/              # VPC, GKE, Cloud SQL, AR, IAM, images
  manifests/              # K8s SA, ConfigMap, Secret, workloads, Ingress
docs/                     # Architecture diagrams (this README)
```

---

## Prerequisites

- Docker + Docker Compose (local)
- Python 3.11+ / [uv](https://github.com/astral-sh/uv) (optional local API)
- For production: `gcloud`, `terraform`, `kubectl`, Docker (image build)

### Environment (`backend/.env` for local)

```env
GEMINI_API_KEY=...
# or GOOGLE_API_KEY=...

DATABASE_URL=postgresql://user:pswd@localhost:5432/crm_db

# Optional real email (otherwise send is simulated)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=

# Optional
# GEMINI_FLASH_MODEL=gemini-2.5-flash
# GEMINI_PRO_MODEL=gemini-2.5-pro
# OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
```

Compose overrides DB host to the `crm_db` service:

```text
DATABASE_URL=postgresql://user:pswd@crm_db:5432/crm_db
```

---

## Local deployment (Docker Compose)

```bash
# Build & start frontend (:8080), backend, Postgres
docker compose up -d --build

# Seed leads, transcript logs, OTel schema, and embeddings
docker compose --profile seed run --rm seed
```

| Service | Host ports | Role |
|---------|------------|------|
| `frontend` | **8080:80** | React UI + `/api` proxy |
| `backend` | none | FastAPI / ADK / HITL / OTel |
| `crm_db` | **5432** | Postgres 17 + pgvector |
| `seed` | — | One-shot Job equivalent |

Open **http://localhost:8080**.

Stop:

```bash
docker compose down
```

---

## Production deployment (GKE)

`deploy.sh` drives the full path:

1. **Terraform** (`infrastructure/terraform`) — VPC/subnet `10.0.0.0/20`, GKE, Cloud SQL (private), Artifact Registry, IAM / Workload Identity, DNS + global IP; build & push **backend / frontend / seed** images  
2. **kubectl** — namespace `fortified-crm-fleet`  
3. **Manifests** (`infrastructure/manifests`) — ServiceAccount, ConfigMap, Secret, Deployments/Services, Seed Job, FrontendConfig, ManagedCertificate, Ingress  
4. Wait for rollouts + seed Job completion  

```bash
# Optional overrides
export TF_VAR_gcp_project_name=agentic-hackerton
export TF_VAR_region=europe-west3

sh deploy.sh
# Enter image tag when prompted (e.g. v1.0.1)
```

After deploy, the UI is available at:

```text
https://fortified-crm-fleet.wolfcore.app
```

(Ingress + Google Managed Certificate; ensure DNS A record points at the reserved global IP.)

### Manifest apply order (reference)

1. `others/serviceaccount.yaml`  
2. `configs/configmap.yaml` · `configs/secret.yaml`  
3. `workload/backend/*` · `workload/frontend/*`  
4. `workload/seed/job.yaml` (delete Job first to re-run)  
5. `network/frontend.yaml` · `managed-certificate.yaml` · `ingress.yaml`  

---

## API surface

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness / DB check |
| `GET` | `/api/v1/lead-filters` | Distinct genre / status / churn |
| `GET` | `/api/v1/leads` | Filtered lead list |
| `GET` | `/api/v1/leads/{id}` | Single lead |
| `POST` | `/api/v1/crm/run` | Run outreach / update / summarize |
| `POST` | `/api/v1/crm/human-decision` | Resume HITL (`approve` \| `reject`) |
| `GET` | `/api/v1/telemetry` | List pipeline OTel runs |
| `GET` | `/api/v1/telemetry/{run_id}` | One run + node spans |

Example:

```bash
curl -s http://localhost:8080/api/v1/crm/run \
  -H 'Content-Type: application/json' \
  -d '{"action":"summarize","lead_id":"L101"}'
```

---

## Data & RAG

| Table | Purpose |
|-------|---------|
| `leads` | CRM profile, qualification, status, last outreach, churn |
| `transcript_logs` | Historical player chats |
| `transcript_embeddings` | pgvector (384-d, `BAAI/bge-small-en-v1.5`) |
| `otel_pipeline_runs` / `otel_node_spans` | Cost & latency telemetry |

RAG retrieval (`helper_scripts/vector_search.py`) is also exposed as an ADK `FunctionTool` on the outreach agent.

---

## Tech stack

| Area | Choice |
|------|--------|
| Agents | Google ADK · Gemini 3.5 Flash / 2.5 Pro |
| API | FastAPI · Uvicorn |
| UI | React 19 · Vite · Tailwind · nginx |
| Data | Postgres · pgvector · FastEmbed |
| Observability | OpenTelemetry (console + optional OTLP) |
| Local | Docker Compose |
| Prod | Terraform · GKE · Cloud SQL · Artifact Registry · Ingress |

---

## License / notes

- HITL checkpoints are **in-process** (`InMemorySessionService`). Multi-replica backends need sticky sessions or a shared store for pause/resume.  
- Seed Job is idempotent-oriented; re-running deletes and recreates the Job.  
- Keep secrets out of git (`backend/.env`, `manifests` secrets with real keys).  
