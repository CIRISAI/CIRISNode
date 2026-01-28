# **CIRISNode – Functional Specification (REST-Only, Minimal Edition)**

*Version 1.4 · 2026-01-28*

---

## 1 Purpose & Scope

CIRISNode is the **single REST back-end** for CIRIS-aligned agents.
It delivers:

1. **Alignment benchmarking** – Hendrycks Ethics (HE-300) and **SimpleBench** via REST.
   - *Implementation Details:* `POST /he300` returns **six** benchmark IDs. Each ID yields **50** prompts when queried via `/bench/he300/prompts?benchmark_id=…`. Agents submit answers to `/bench/he300/answers` and fetch signed results from `/bench/he300/results/{benchmark_id}`. `POST /simplebench` returns all **10** prompts in one call with a similar upload flow.
2. **Wisdom-Based Deferral (WBD)** – queue → WA review → resolution → audit.
   - *Implementation Details:* WBD workflows are managed via endpoints in `cirisnode/api/wa/routes.py`, including task submission, listing, resolution, and SLA auto-escalation.
3. **Immutable audit logging** – every benchmark, WBD decision, and agent event.
   - *Implementation Details:* Audit logging is implemented in `cirisnode/api/audit/routes.py` and integrated with benchmark, WBD, and agent event endpoints.

No chat bridges, SSI, Matrix, or telemetry live here; those belong in separate micro-services. A2A and MCP protocols are supported for agent-to-agent communication and tool access.

---

## 2 Core Capabilities

| #   | Capability       | What it Does                                                                                                      |
| --- | ---------------- | ----------------------------------------------------------------------------------------------------------------- |
| 2.1 | **HE-300**       | `POST /he300` → six IDs → 50 prompts each via `/bench/he300/prompts`. Answers uploaded and results fetched per ID. |
|     |                  | *Implementation Details:* Prompts sampled from Hendrycks Ethics. Results are signed using Ed25519. |
| 2.2 | **SimpleBench**  | `POST /simplebench` returns 10 prompts in one call; upload answers to `/bench/simplebench/answers`. |
|     |                  | *Implementation Details:* Uses `simple_bench_public.json`; minimal turnaround for health checks. |
| 2.3 | **WBD**          | Accept deferral packages from agents; expose WA queue & resolution endpoints; auto-escalate on SLA breach (24 h). |
|     |                  | *Implementation Details:* Endpoints in `cirisnode/api/wa/routes.py`; SLA auto-escalation implemented.              |
| 2.4 | **Audit**        | Append-only log (timestamp, actor, event\_type, SHA-256 hash, raw JSON); downloadable.                            |
|     |                  | *Implementation Details:* Endpoints in `cirisnode/api/audit/routes.py`; logs are downloadable.                     |
| 2.5 | **Agent Events** | Endpoint for agents to push Task/Thought/Action events for observability.                                         |
|     |                  | *Implementation Details:* Endpoint in `cirisnode/api/agent/routes.py`.                                             |
| 2.6 | **A2A Protocol** | Agent-to-Agent protocol for AgentBeats competition compatibility. JSON-RPC 2.0 endpoint for task management.       |
|     |                  | *Implementation Details:* Endpoints in `cirisnode/api/a2a/`. Agent Card at `/.well-known/agent.json`.              |
| 2.7 | **MCP Server**   | Model Context Protocol server exposing HE-300 evaluation as tools and resources for AI agent integration.          |
|     |                  | *Implementation Details:* FastMCP server in `cirisnode/mcp/`. Tools: scenario listing, batch evaluation, reports.  |

---

## 3 REST API (JSON)

> All routes return `application/json`.
> Bearer JWT (RS256) required except `/health` and `/metrics`.

| Method   | Path                                        | Purpose                                                   |               |
| -------- | ------------------------------------------- | --------------------------------------------------------- | ------------- |
| **GET**  | `/health`                                  | `{"status":"ok","version":"1.3.0","pubkey":"…"}`             |               |
| **POST** | `/he300`                                   | Start HE-300 and receive six `benchmark_id` values.       |               |
| **GET**  | `/bench/he300/prompts`                     | Query `benchmark_id`,`model_id`,`agent_id` → 50 prompts.  |               |
| **PUT**  | `/bench/he300/answers`                     | Upload answers `{benchmark_id,model_id,agent_id,answers}`.|               |
| **GET**  | `/bench/he300/results/{benchmark_id}`      | Fetch signed results for that ID.                         |               |
| **POST** | `/simplebench`                             | Return all 10 prompts and scores in one call.             |               |
| **GET**  | `/bench/simplebench/prompts`               | (Optional) fetch the 10 prompts separately.               |               |
| **PUT**  | `/bench/simplebench/answers`               | Upload answers for SimpleBench.                           |               |
| **GET**  | `/bench/simplebench/results/{benchmark_id}`| Retrieve stored SimpleBench results.                      |               |
| **POST** | `/wa/{service}`                            | Invoke a Wise Authority service.                          |               |
| **POST** | `/chaos`                                   | Execute chaos scenarios for an agent.                     |               |
| **POST** | `/events`                                  | Agents push event logs.                                   |               |
| **GET**  | `/metrics`                                 | Prometheus metrics (public).                              |               |
| **GET**  | `/.well-known/agent.json`                  | A2A Agent Card discovery (public).                        |               |
| **POST** | `/a2a`                                     | A2A JSON-RPC 2.0 (message/send, tasks/get, etc.).         |               |
| **GET**  | `/a2a/tasks/{id}/stream`                   | SSE streaming for A2A task progress.                      |               |
| **GET**  | `/mcp/sse`                                 | MCP SSE transport endpoint.                               |               |
| **POST** | `/mcp/messages/`                           | MCP message endpoint for tool calls.                      |               |

*A2A and MCP transports added for AgentBeats compatibility.*
*Implementation Details:* All API endpoints are implemented as specified and return `application/json`. JWT authentication (RS256) is required for all endpoints except `/health` and `/metrics`.

---

## 4 Data Model (SQLModel · SQLite→Postgres)

| Table          | Key Columns                                                                      | Notes                 |
| -------------- | -------------------------------------------------------------------------------- | --------------------- |
| `jobs`         | id, type(`he300`/`simplebench`), status, started\_at, finished\_at, results\_url |                       |
| `wbd_tasks`    | id, agent\_task\_id, status(`open`/`resolved`/`sla_breached`), decision, comment | 24 h SLA auto-breach. |
| `audit`        | id, ts, actor, event\_type, payload\_sha256, raw\_json                           | Append-only.          |
| `agent_events` | id, node\_ts, agent\_uid, event\_json                                            | Raw push from agents. |

Large result JSON stored in object storage (disk → S3/GCS).
*Implementation Details:* Database schema (`cirisnode/db/schema.sql`) is compatible with SQLite and Postgres. A migration script (`cirisnode/db/migrate_to_postgres.py`) is provided. Sensitive fields are encrypted at rest.

---

## 5 Runtime Architecture

* **FastAPI** – stateless REST.
* **Celery + Redis** – async job runner for benchmarks.
* **Postgres / SQLite** – metadata + audit.
* **Next.js UI** (optional) – dashboard under `/ui` but calls the same REST.
* **Ed25519 signer** – each node signs benchmark bundles; pubkey served at `/health`.
* **A2A Server** – JSON-RPC 2.0 endpoint with SSE streaming for task progress.
* **MCP Server** – FastMCP-based Model Context Protocol server for AI agent tool access.

Docker Compose: `api`, `worker`, `redis`, `db`, `ui` (optional).
*Implementation Details:* All components are implemented as specified. FastAPI (`cirisnode/main.py`), Celery + Redis (`cirisnode/celery_app.py`), Postgres/SQLite (`cirisnode/database.py`), Next.js UI (`ui/`), Ed25519 signer (`cirisnode/utils/signer.py`), and Docker Compose (`docker-compose.yml`) are all in place.

---

## 6 Security

* JWT (RS256) 15 min TTL; `/auth/refresh` TBD.
  *Implementation Details:* JWT authentication with RS256, 15-min TTL, and `/auth/refresh` endpoint are implemented in `cirisnode/api/auth/`.
* HTTPS only in prod; HSTS.
  *Implementation Details:* Guidance added to `README.md` for HTTPS/HSTS in production.
* Audit row hash guarantees tamper evidence.
  *Implementation Details:* SHA-256 hash of payload stored in audit logs.
* Unit + integration tests ≥ 90 % route coverage (CI).
  *Implementation Details:* Test suite created in `tests/` covering all API modules.

---

## 7 Operational Limits

```
MAX_THOUGHT_DEPTH = 7
MAX_PONDER_COUNT  = 7
DMA_RETRY_LIMIT   = 3
WBD_SLA_HOURS     = 24
```
*Implementation Details:* Operational limits are defined in `cirisnode/config.py`.

---

## 8 Observability

* Standard Python logging (`LOG_LEVEL` env).
* `/metrics` for Prometheus.
* OpenTelemetry traces optional (`OTEL_EXPORTER_OTLP_ENDPOINT`).
*Implementation Details:* Standard Python logging is used. `/metrics` endpoint for Prometheus is implemented in `cirisnode/main.py`. OpenTelemetry is optional.

---

## 9 Deployment

```bash
git clone cirisai/cirisnode
docker compose up          # local dev
```

GitHub Actions → build image → push to GHCR.
Helm chart `cirisnode-0.2.0` for Kubernetes.
*Implementation Details:* `README.md` and `docker-compose.yml` align with deployment instructions.

---

## 10 Open Items

* Role-based WA auth (scopes).
* Chaos-level config JSON-schema.
* S3/GCS migration tool for result artefacts.
  *Implementation Details:* Migration script `cirisnode/utils/storage_migration.py` created.

---

**CIRISNode v1.4** – REST nucleus for alignment benchmarking, WBD governance, audit, and AgentBeats-compatible A2A/MCP integration.
