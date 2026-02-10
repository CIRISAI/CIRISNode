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
| **admin** | `cirisnode/api/admin/` | DEPRECATED tier writes + authority profile CRUD + frontier sweep |
| **wa/wbd** | `cirisnode/api/wa/`, `cirisnode/api/wbd/` | WBD task submission, routing, resolution |
| **notifications** | `cirisnode/services/notifications.py` | Email + Discord + in-app notification dispatcher |

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

## Auth & RBAC (3-Tier)

- **User auth**: JWT signed with `JWT_SECRET` (shared with ethicsengine-site via `NEXTAUTH_SECRET`)
- **Service auth**: JWT with `role: "service"` claim, used by PortalClient to call Portal API
- **Admin auth**: JWT with `role: "admin"` claim, signed by Portal API using shared `JWT_SECRET`
- **Agent auth**: `X-Agent-Token` header for agent event POST/GET; admin JWT for DELETE/PATCH

### Roles

| Role | Who | Access |
|------|-----|--------|
| `admin` | @ciris.ai accounts (auto-created) | Full access + user management |
| `wise_authority` | Invited external users | Read scores/evals/audit + resolve assigned WBD tasks |
| `anonymous` | Everyone else | No access |

### Key Auth Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/auth/check-access?email=` | None | Check if email is allowed + return role |
| POST | `/api/v1/admin/users/invite` | Admin JWT | Invite user as wise_authority |

### Authority Profile Endpoints (admin-only)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/admin/authorities` | List all authority profiles |
| GET | `/api/v1/admin/authorities/{user_id}` | Get single authority profile |
| PUT | `/api/v1/admin/authorities/{user_id}` | Update expertise, agents, availability, notifications |
| DELETE | `/api/v1/admin/authorities/{user_id}` | Remove authority profile |

### WBD Task Routing

On WBD submit, tasks are auto-routed to authorities based on:
1. Expertise domain match (`domain_hint` vs `expertise_domains`)
2. Agent assignment match (`assigned_agent_ids`)
3. Availability windows (timezone-aware)

Authorities see only tasks assigned to them or unassigned. Admins see all tasks.

### Notifications

Configured per-authority via `notification_config` JSON:
- **Email**: Requires `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` env vars
- **Discord**: Webhook URL per authority
- **In-App**: UI polls `/api/v1/wbd/tasks` filtered by assignment

## Database

### PostgreSQL (async, via asyncpg pool)
- `evaluations` — benchmark results (read path, written by Celery workers)
- `tenant_tiers` — DEPRECATED: tier per tenant (no longer read by quota.py)
- `agent_profiles` — agent registration data
- `authority_profiles` — expertise, availability, notification config for wise authorities

### SQLite (sync, via cirisnode/database.py)
- `users` — username, role, OAuth data
- `wbd_tasks` — WBD task queue with routing fields (assigned_to, domain_hint)
- `audit_logs` — immutable audit trail
- `agent_tokens`, `agent_events`, `config`, `jobs`

PostgreSQL migrations auto-run at startup via `cirisnode/db/migrator.py`.
SQLite schema auto-migrates new columns on first connection via `cirisnode/database.py`.

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

### Optional Env Vars for Notifications

```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@ciris.ai
SMTP_PASS=secret
SMTP_FROM=noreply@ciris.ai
```

## Frontier Sweep Management

Admin endpoints for running HE-300 benchmarks across frontier LLMs.

### Key Files

| File | Purpose |
|------|---------|
| `cirisnode/api/admin/frontier_routes.py` | Model registry CRUD + sweep launch/progress |
| `cirisnode/db/migrations/007_frontier_sweep.sql` | Adds `api_base_url`, `default_model_name` to `frontier_models` |

### Endpoints (all require admin JWT)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/admin/frontier-models` | Register/update a model |
| GET | `/api/v1/admin/frontier-models` | List registered models |
| DELETE | `/api/v1/admin/frontier-models/{model_id}` | Remove a model |
| POST | `/api/v1/admin/frontier-sweep` | Launch sweep (always 300 scenarios) |
| GET | `/api/v1/admin/frontier-sweep/{sweep_id}` | Sweep progress |
| GET | `/api/v1/admin/frontier-sweeps` | List recent sweeps |

### Setting Up Frontier API Keys

```bash
# In .env or container environment
FRONTIER_API_KEYS='{"openai":"sk-proj-...","anthropic":"sk-ant-...","google":"AIza..."}'
```

Only providers with registered models need keys. Provider matching is case-insensitive.

### Running a Frontier Sweep

```bash
# 1. Generate admin JWT
ADMIN_JWT=$(python3 -c "import jwt,time; print(jwt.encode({'sub':'admin@ciris.ai','role':'admin','iat':int(time.time()),'exp':int(time.time())+3600}, '$JWT_SECRET', algorithm='HS256'))")

# 2. Register models (one-time)
curl -X POST https://node.ciris.ai/api/v1/admin/frontier-models \
  -H "Authorization: Bearer $ADMIN_JWT" -H "Content-Type: application/json" \
  -d '{"model_id":"gpt-4o","display_name":"GPT-4o","provider":"OpenAI","api_base_url":"https://api.openai.com/v1","default_model_name":"gpt-4o"}'

# 3. Launch sweep
curl -X POST https://node.ciris.ai/api/v1/admin/frontier-sweep \
  -H "Authorization: Bearer $ADMIN_JWT" -H "Content-Type: application/json" \
  -d '{"concurrency":50}'

# 4. Check progress
curl https://node.ciris.ai/api/v1/admin/frontier-sweep/sweep-abc12345 \
  -H "Authorization: Bearer $ADMIN_JWT"
```

### Sweep Behavior

- Only full HE-300 runs (300 scenarios) are stored as frontier evals
- Results are `visibility='public'` and appear on the scores page
- Scenarios loaded once with shared seed for cross-model comparability
- Models run with bounded parallelism (2 concurrent) to avoid rate limits
- Redis caches (`scores:frontier`, `embed:scores`, per-model) invalidated after sweep
- Progress tracked via `evaluations` rows where `trace_id LIKE '{sweep_id}/%'`

## Admin UI (Next.js)

Located at `ui/`. Role-aware dashboard with page-level access control.

### Page Access Matrix

| Page | Route | Admin | Authority |
|------|-------|-------|-----------|
| Scores | `/` | Full | Read |
| Frontier Sweep | `/frontier` | Full | Hidden |
| Evaluations | `/evaluations` | Full | Read |
| Agent Oversight | `/oversight` | Full | View + resolve assigned WBD |
| Audit | `/audit` | Full | Read |
| System | `/system` | Full | Hidden |
| Users | `/users` | Full | Hidden |

### Key UI Files

| File | Purpose |
|------|---------|
| `ui/src/app/api/auth/[...nextauth]/route.ts` | NextAuth config — calls check-access API |
| `ui/src/components/AdminNav.tsx` | Role-filtered nav + WBD badge |
| `ui/src/components/RoleGuard.tsx` | Page-level role guard |
| `ui/src/app/users/page.tsx` | User management + authority profile editor |
| `ui/src/app/oversight/page.tsx` | WBD tasks with assignment column |
| `ui/src/types/next-auth.d.ts` | Session/JWT type augmentation for role |

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
