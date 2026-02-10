# CIRISNode - Claude Code Context

## Role

Benchmark execution gateway + evaluation read APIs. **NO finance/billing logic.** Stripe lives exclusively in Portal API.

## Tech Stack

- **Language**: Python 3.12, FastAPI, asyncpg
- **Database**: PostgreSQL (evaluations, tenant_tiers, agent_profiles)
- **Queue**: Redis + Celery for async benchmark execution
- **Auth**: JWT (HS256) — `JWT_SECRET` env var
- **Deployment**: `prod-us` container via CIRISCore Ansible

## Key Modules

| Module | Path | Purpose |
|--------|------|---------|
| **agentbeats** | `cirisnode/api/agentbeats/` | Benchmark execution + tiered quota enforcement |
| **evaluations** | `cirisnode/api/evaluations/` | Evaluation read, delete, report endpoints |
| **scores** | `cirisnode/api/scores/` | Public leaderboard |
| **admin** | `cirisnode/api/admin/` | Tier DB writes only (called by Portal API) |
| **quota** | `cirisnode/api/agentbeats/quota.py` | Tiered usage limits (community/pro/enterprise) |

## Auth

- **User auth**: JWT signed with `JWT_SECRET` (shared with ethicsengine-site via `NEXTAUTH_SECRET`)
- **Admin auth**: JWT with `role: "admin"` claim, signed by Portal API using shared `JWT_SECRET`
- **Agent auth**: `X-Agent-Token` header for agent event POST/GET; admin JWT for DELETE/PATCH

## Database

PostgreSQL tables:
- `evaluations` — benchmark results (read path, written by Celery workers)
- `tenant_tiers` — tier + stripe_customer_id per tenant (written by admin endpoint)
- `agent_profiles` — agent registration data

Migrations auto-run at startup via `cirisnode/db/migrator.py`.

## Integrations

- **Receives from**: Portal API (admin JWT for tier management)
- **Serves to**: ethicsengine-site (evaluation data, scores, quota checks)
- **Does NOT call**: Stripe, billing services, or Portal API

## NOT Responsible For

- Stripe SDK calls or customer management (that's Portal API)
- Billing, subscriptions, or payment processing
- Customer creation or Stripe customer sync

## Dev Setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env  # Set JWT_SECRET, DATABASE_URL, REDIS_URL
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
  |                            |           |
  | (DB: evals,               |           |
  |  tenant_tiers)            |           |
  v                           v           v
PostgreSQL               CIRISNode    Stripe
                         (admin JWT   (system of
                          for tiers)   record)
```
