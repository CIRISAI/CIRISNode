# CIRISNode - Claude Code Context

## Role

Benchmark execution gateway + evaluation read APIs. **NO finance/billing logic.** Stripe lives exclusively in Portal API. CIRISNode delegates all billing/gating decisions to Portal API via the standing endpoint.

## Tech Stack

- **Language**: Python 3.12, FastAPI, asyncpg
- **Database**: PostgreSQL only (via asyncpg pool)
- **Queue**: Redis + Celery for async benchmark execution
- **Auth**: JWT (HS256) — `JWT_SECRET` env var
- **Deployment**: Docker → GHCR → Watchtower auto-deploy (see CI/CD section)

## Key Modules

| Module | Path | Purpose |
|--------|------|---------|
| **portal_client** | `cirisnode/services/portal_client.py` | Portal API client for standing checks (60s cache) |
| **quota** | `cirisnode/services/quota.py` | Quota check — calls Portal API + counts local evals |
| **evaluations** | `cirisnode/api/evaluations/` | Evaluation read, delete, report, usage endpoints |
| **scores** | `cirisnode/api/scores/` | Public scores (aggregate: min 5 evals/model, trends at 10) |
| **billing** | `cirisnode/api/billing/` | Plan display + billing proxy to Portal API |
| **admin** | `cirisnode/api/admin/` | Authority profile CRUD + frontier sweep (tenant tier management removed) |
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

- **PortalClient** (`cirisnode/services/portal_client.py`): Async httpx client, service JWT auth, 60s cache
- **check_quota()** (`cirisnode/services/quota.py`): Calls PortalClient, counts local evals, raises QuotaDenied
- **count_evals_in_window()**: SQL count on evaluations table
- If Portal API unreachable: returns standing="degraded", benchmark denied (503)
- `tenant_tiers` table removed (Portal API is source of truth for tier/standing)

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

All tables in a single PostgreSQL database (async, via asyncpg pool). Migrations auto-run at startup via `cirisnode/db/migrator.py`.

### Tables

- `evaluations` — benchmark results (written by Celery workers)
- `frontier_models` — display metadata for frontier sweep scores
- `agent_profiles` — agent registration data
- `users` — username, role, OAuth data
- `wbd_tasks` — WBD task queue with routing fields (assigned_to, domain_hint)
- `authority_profiles` — expertise, availability, notification config for wise authorities
- `audit_logs` — immutable audit trail
- `agent_tokens`, `agent_events`, `config`, `jobs`
- `covenant_public_keys`, `covenant_traces`, `covenant_invocations`

### Note: `tenant_tiers` table removed
Tier/standing decisions now come exclusively from Portal API (`GET /api/v1/standing/{actor}`).

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
| GET | `/api/v1/admin/frontier-keys` | List configured API key providers (masked previews) |
| GET | `/api/v1/admin/logs` | Node application logs (ring buffer, filterable) |
| POST | `/api/v1/admin/frontier-models` | Register/update a model (with cost + reasoning fields) |
| GET | `/api/v1/admin/frontier-models` | List registered models |
| DELETE | `/api/v1/admin/frontier-models/{model_id}` | Remove a model |
| POST | `/api/v1/admin/frontier-sweep` | Launch sweep (always 300 scenarios) |
| GET | `/api/v1/admin/frontier-sweep/{sweep_id}` | Sweep progress |
| GET | `/api/v1/admin/frontier-sweep/{sweep_id}/stream` | SSE progress stream |
| POST | `/api/v1/admin/frontier-sweep/{sweep_id}/pause` | Pause a running sweep |
| POST | `/api/v1/admin/frontier-sweep/{sweep_id}/resume` | Resume a paused sweep |
| POST | `/api/v1/admin/frontier-sweep/{sweep_id}/cancel` | Cancel a sweep |
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
- Models run with bounded parallelism (1 per provider, 3 global) to avoid rate limits
- Protocol adapters retry HTTP 429/529 with intelligent backoff (Retry-After header → body hints → exponential 5-80s), max 5 retries
- SSE streaming via `GET /frontier-sweep/{id}/stream` (fetch+ReadableStream, not EventSource)
- Pause/resume/cancel controls via in-memory `_sweep_controls` dict
- Redis caches (`scores:frontier`, `embed:scores`, per-model) invalidated after sweep
- Progress tracked via `evaluations` rows where `trace_id LIKE '{sweep_id}/%'`

### Cost Estimation

- Models store `cost_per_1m_input` and `cost_per_1m_output` (USD per 1M tokens)
- UI estimates sweep cost: 300 scenarios * ~150 input + ~100 output tokens each
- Known model pricing auto-fills when adding models in the UI

### Reasoning Effort

- Models can be flagged `supports_reasoning=true` with `reasoning_effort` (low/medium/high)
- For o-series models (o3, o3-mini, o4-mini), passes `{"reasoning": {"effort": value}}` in API call
- Reasoning models skip `temperature` and use `max_completion_tokens` instead of `max_tokens`

### Node Logs

- In-memory ring buffer (2000 entries) attached to root Python logger
- `GET /api/v1/admin/logs?level=ERROR&pattern=SWEEP&limit=200`
- UI panel with level filter, pattern search, and 5s auto-refresh

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

Requires a PostgreSQL test database:
```bash
DATABASE_URL=postgresql://localhost/cirisnode_test .venv/bin/python -m pytest tests/ -v
```

## CI/CD

Continuous deployment pipeline: push to `main` → Docker build → auto-deploy to prod.

### Pipeline (`.github/workflows/deploy.yml`)

1. **Trigger**: Push to `main` branch
2. **Build**: GitHub Actions builds Docker image using `Dockerfile` (Python 3.10-slim, uvicorn with 4 workers)
3. **Push**: Image pushed to `ghcr.io/cirisai/cirisnode` with tags `latest` + commit SHA
4. **Deploy**: Watchtower on prod-us VPS polls GHCR, pulls new `latest` image, restarts container automatically

### Key Details

- **Registry**: `ghcr.io/cirisai/cirisnode`
- **Auth**: `GITHUB_TOKEN` (automatic via GitHub Actions `packages: write` permission)
- **Build cache**: GitHub Actions cache (`type=gha`) for faster rebuilds
- **Image tags**: `latest` (rolling) + short SHA (immutable, for rollback)
- **No manual deploy step**: Watchtower handles pull + restart on the VPS
- **Commit to main = deploy to prod** — all changes on `main` go live automatically

### Docker

- `Dockerfile`: Python 3.10-slim, installs requirements, runs uvicorn on port 8000
- `docker-compose.yml`: Full stack (api, celery worker, postgres, redis, admin UI) — used for local/reference, prod uses individual containers

### Rollback

To rollback, push a revert commit to `main` or manually pull a specific SHA tag on the VPS:
```bash
docker pull ghcr.io/cirisai/cirisnode:<sha>
```

## Agent-Registry Integration (E2E QA 2026-02-13)

### How Agents Authenticate

Agents authenticate with CIRISNode via Ed25519 signatures, NOT tokens:

1. Signing keys generated at CIRISPortal (portal.ciris.ai) → stored in CIRISRegistry
2. Private key downloaded once at generation, placed in agent's `data/agent_signing.key`
3. Agent registers public key with CIRISNode at startup (`POST /api/v1/covenant/public-keys`)
4. CIRISNode auto-discovers org_id via fingerprint lookup against Registry (`GetPublicKeys` with `ed25519_fingerprint`)
5. All subsequent traces and deferrals carry inline Ed25519 signatures
6. CIRISNode verifies each signature against the registered key

**No org_id config needed on the agent** — CIRISNode computes SHA-256(public_key) and looks up the fingerprint in Registry to discover org_id and verification status automatically.

**Key registration = covenant_metrics consent**: No separate consent flow needed.

### Agent Event Endpoints

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | `/api/v1/covenant/public-keys` | X-Agent-Token (optional) | Register agent signing key |
| PATCH | `/api/v1/covenant/public-keys/{key_id}` | Admin JWT | Admin: update org_id, registry_verified, registry_status |
| POST | `/api/v1/covenant/events` | Ed25519 inline signature | Batch covenant traces |
| POST | `/api/v1/wbd/submit` | Ed25519 signature | Submit signed deferral |
| GET | `/api/v1/wbd/tasks/{id}` | None | Poll deferral resolution |
| POST | `/api/v1/agent/events` | X-Agent-Token | Post agent events |

### Admin Key Management

The `PATCH /api/v1/covenant/public-keys/{key_id}` endpoint allows admins to override key verification status. Useful for QA and when the automatic Registry cross-validation path is not yet complete.

**Request body** (all fields optional):
```json
{
  "org_id": "73bddb21-...",
  "registry_verified": true,
  "registry_status": "active"
}
```

**Note**: `registry_verified` must be `true` for an agent's Ed25519 signatures to be accepted on WBD submissions.

### Admin UI

The CIRISNode admin UI is at **admin.ethicsengine.org** (NOT node.ciris.ai/docs). Use it for:
- WBD task resolution (Agent Oversight page)
- User/authority management
- Audit log viewing
- System status

### Trace Levels

CIRISNode receives **full_traces** (via cirisnode adapter). CIRISLens receives **detailed** traces (via covenant_metrics adapter). These are separate concerns.

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

## Deployment Notes (2026-02-14)

**SQLite fully removed.** CIRISNode previously used SQLite for auth/agent/WBD tables and PostgreSQL for benchmarking. As of this release, all tables are in PostgreSQL via asyncpg. Key changes:

- **New migration `001_ensure_core_tables.sql`** runs automatically at startup (via `migrator.py`). Uses `CREATE TABLE IF NOT EXISTS` — safe on existing databases.
- **`database.py` and `init_db.py` deleted** — no more SQLite connection manager or schema init.
- **Dockerfile simplified** — no longer runs `init_db.py` before uvicorn.
- **All route files** converted from sync SQLite (`?` params, `.fetchone()`, `Depends(get_db)`) to async asyncpg (`$N` params, `await conn.fetchrow()`, `await get_pg_pool()`).
- **Dead code removed** — `agentbeats/`, `Veilid_*`, unused schemas, duplicate utils (~2500 lines deleted).
- **Tests require PostgreSQL** — `DATABASE_URL=postgresql://localhost/cirisnode_test`

No API contract changes. All endpoints return the same shapes. Frontend services (ethicsengine-site, ethicsengine-portal, ethicsengine-portal-api) are unaffected.

## Domain Separation

CIRISNode has two independent logical domains, all in PostgreSQL:

| Domain | Router Files | Key Tables |
|--------|-------------|------------|
| **Wise Authority** | `api/wa/`, `api/wbd/`, `api/admin/authority_routes.py` | `wbd_tasks`, `authority_profiles`, `covenant_public_keys` |
| **Benchmarking** | `api/benchmarks/`, `api/evaluations/`, `api/scores/`, `api/admin/frontier_routes.py` | `evaluations`, `frontier_models`, `agent_profiles` |
| **Agent Infra** | `api/agent/`, `api/covenant/` | `agent_events`, `covenant_public_keys`, `covenant_traces` |
| **Shared** | `auth/`, `api/auth/`, `api/audit/`, `api/config/`, `api/health/` | `users`, `audit_logs` |

No cross-domain data dependencies exist between WA and Benchmarking. Auth module (`cirisnode/auth/`) is the single source of truth for all JWT/role/agent-token validation.
