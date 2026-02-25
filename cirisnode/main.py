import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# ── Shared Infrastructure ──
from cirisnode.api.health.routes import router as health_router
from cirisnode.api.auth.routes import auth_router
from cirisnode.api.config.routes import config_router
from cirisnode.api.audit.routes import audit_router

# ── Agent Infrastructure (Ed25519 signatures, events, A2A) ──
from cirisnode.api.agent.routes import agent_router
from cirisnode.api.accord.routes import accord_router
from cirisnode.api.a2a.routes import a2a_router, agent_card_router

# ── Wise Authority (WBD task submission, resolution, authority mgmt) ──
from cirisnode.api.wa.routes import wa_router
from cirisnode.api.wbd.routes import wbd_router
from cirisnode.api.admin.authority_routes import authority_router

# ── Agent Profiles (saved agent configurations) ──
from cirisnode.api.agent_profiles.routes import agent_profiles_router

# ── Benchmarking (eval execution, scores, leaderboard, frontier sweep) ──
from cirisnode.api.benchmarks.routes import simplebench_router, benchmarks_router
from cirisnode.api.scores.routes import scores_router
from cirisnode.api.evaluations.routes import evaluations_router, usage_router
from cirisnode.api.admin.frontier_routes import frontier_router

# ── Billing (proxy to Portal API) ──
from cirisnode.api.billing.routes import billing_router

# ── LLM/Ollama (test endpoints) ──
from cirisnode.api.ollama.routes import ollama_router
from cirisnode.api.llm.routes import llm_router

# ── MCP Server ──
from cirisnode.mcp.transport import mcp_app

from cirisnode.utils.log_buffer import install_log_buffer

# Install ring buffer log handler before anything else logs
install_log_buffer(capacity=2000)


# ---------------------------------------------------------------------------
# Lifecycle — init/close PostgreSQL pool and Redis on startup/shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    from cirisnode.db.pg_pool import get_pg_pool, close_pg_pool
    from cirisnode.utils.redis_cache import get_redis, close_redis
    pool = await get_pg_pool()
    await get_redis()
    # Run pending SQL migrations (best-effort — logs errors, doesn't crash)
    try:
        from cirisnode.db.migrator import run_migrations
        await run_migrations(pool)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Migration runner failed: %s", exc)
    yield
    await close_pg_pool()
    await close_redis()


app = FastAPI(lifespan=lifespan)

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "https://node0.ciris.ai")

_allowed_origins = [
    FRONTEND_ORIGIN,
    "https://ciris.ai",
    "https://www.ciris.ai",
    "https://node.ciris.ai",
    "https://ethicsengine.org",
    "https://www.ethicsengine.org",
    "https://admin.ethicsengine.org",
    "https://portal.ethicsengine.org",
    "https://api.portal.ethicsengine.org",
]
# Only allow localhost in development
if os.getenv("NODE_ENV", "production") == "development":
    _allowed_origins.append("http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-API-Key", "X-Agent-Token", "stripe-signature"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ── Shared Infrastructure ──
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(config_router)
app.include_router(audit_router)

# ── Agent Infrastructure (Ed25519 signatures, events, A2A) ──
app.include_router(agent_router)
app.include_router(accord_router)
app.include_router(agent_card_router)   # /.well-known/agent.json
app.include_router(a2a_router)          # /a2a JSON-RPC

# ── Wise Authority (WBD task submission, resolution, authority mgmt) ──
app.include_router(wa_router)
app.include_router(wbd_router)
app.include_router(authority_router)    # /api/v1/admin/authorities CRUD

# ── Agent Profiles (saved agent configurations) ──
app.include_router(agent_profiles_router)

# ── Benchmarking (eval execution, scores, leaderboard, frontier sweep) ──
app.include_router(simplebench_router)
app.include_router(benchmarks_router)
app.include_router(scores_router)       # /api/v1/scores, /leaderboard, /embed
app.include_router(evaluations_router)  # /api/v1/evaluations
app.include_router(usage_router)        # /api/v1/usage
app.include_router(frontier_router)     # /api/v1/admin/frontier-models, /sweep

# ── Billing (proxy to Portal API) ──
app.include_router(billing_router)

# ── LLM/Ollama (test endpoints) ──
app.include_router(ollama_router)
app.include_router(llm_router)

# ── MCP Server ──
app.mount("/mcp", mcp_app)
