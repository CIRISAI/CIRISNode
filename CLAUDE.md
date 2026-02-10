# CIRISNode - Claude Code Context

## Role

Benchmark execution gateway + evaluation read APIs. **NO finance/billing logic.** Stripe lives exclusively in Portal API. CIRISNode delegates all billing/gating decisions to Portal API via the standing endpoint.

## Tech Stack

- **Language**: Python 3.12, FastAPI, asyncpg
- **Database**: PostgreSQL (evaluations, tenant_tiers, agent_profiles)
- **Queue**: Redis + Celery for async benchmark execution
- **Auth**: JWT (HS256) — `JWT_SECRET` env var
- **Deployment**: `prod-us` container via CIRISCore Ansible

## Key Modules

| Module | Path | Purpose |
|--------|------|---------|
| **agentbeats** | `cirisnode/api/agentbeats/` | Benchmark execution + quota enforcement |
| **portal_client** | `cirisnode/api/agentbeats/portal_client.py` | Portal API client for standing checks (60s cache) |
| **quota** | `cirisnode/api/agentbeats/quota.py` | Quota check — calls Portal API + counts local evals |
| **evaluations** | `cirisnode/api/evaluations/` | Evaluation read, delete, report, usage endpoints |
| **scores** | `cirisnode/api/scores/` | Public leaderboard |
| **billing** | `cirisnode/api/billing/` | Plan display + billing proxy to Portal API |
| **admin** | `cirisnode/api/admin/` | DEPRECATED: tier DB writes (no longer read by quota) |

## Quota Architecture (2026-02-10)

CIRISNode no longer decides tiers locally. The flow is:

```
User requests benchmark or usage
    ↓
CIRISNode calls Portal API: GET /api/v1/standing/{actor}
    ↓ (cached 60s in PortalClient)
Portal API looks up Stripe customer → returns tier, standing, limit, window
    ↓
CIRISNode counts local evals in window (evaluations table)
    ↓
CIRISNode compares count vs limit → allow/deny
```

- **PortalClient** (`portal_client.py`): Async httpx client, service JWT auth, 60s cache
- **check_quota()**: Calls PortalClient, counts local evals, raises QuotaDenied
- **count_evals_in_window()**: SQL count on evaluations table
- If Portal API unreachable: returns standing="degraded", benchmark denied (503)
- `tenant_tiers` table is no longer read by quota.py (DEPRECATED)

## Auth

- **User auth**: JWT signed with `JWT_SECRET` (shared with ethicsengine-site via `NEXTAUTH_SECRET`)
- **Service auth**: JWT with `role: "service"` claim, used by PortalClient to call Portal API
- **Admin auth**: JWT with `role: "admin"` claim, signed by Portal API using shared `JWT_SECRET`
- **Agent auth**: `X-Agent-Token` header for agent event POST/GET; admin JWT for DELETE/PATCH

## Database

PostgreSQL tables:
- `evaluations` — benchmark results (read path, written by Celery workers)
- `tenant_tiers` — DEPRECATED: tier per tenant (no longer read by quota.py)
- `agent_profiles` — agent registration data

Migrations auto-run at startup via `cirisnode/db/migrator.py`.

## Integrations

- **Calls**: Portal API (`PORTAL_API_URL`) for actor standing checks (service JWT auth)
- **Serves to**: ethicsengine-site (evaluation data, scores, usage)
- **Does NOT call**: Stripe directly (all billing via Portal API)

## NOT Responsible For

- Stripe SDK calls or customer management (that's Portal API)
- Billing, subscriptions, or payment processing
- Customer creation or Stripe customer sync
- Tier definitions or limits (owned by Portal API)

## Dev Setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env  # Set JWT_SECRET, DATABASE_URL, REDIS_URL, PORTAL_API_URL
.venv/bin/uvicorn cirisnode.main:app --reload --port 8001
```

## Testing

```bash
.venv/bin/python -m pytest tests/ -v
```

## Architecture

```
Users                          Admins (@ciris.ai)
  |                                |
  v                                v
ethicsengine-site           ethicsengine-portal
(ethicsengine.org)          (portal.ethicsengine.org)
  |                                |
  | (all API calls)                | (all API calls)
  v                                v
CIRISNode  <-- YOU ARE HERE  ethicsengine-portal-api
(node.ciris.ai)             (api.portal.ethicsengine.org)
  |    |                       |           |
  |    | GET /standing/{actor} |           |
  |    +---------------------> |           |
  |                            |           |
  | (DB: evals)               |           v
  v                            |        Stripe
PostgreSQL                     |      (system of
                               |       record)
```
