from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from cirisnode.api.audit.routes import audit_router
from cirisnode.api.benchmarks.routes import simplebench_router, benchmarks_router
from cirisnode.api.ollama.routes import ollama_router
from cirisnode.api.wbd.routes import wbd_router
from cirisnode.api.llm.routes import llm_router
from cirisnode.api.health.routes import router as health_router
from cirisnode.api.agent.routes import agent_router
from cirisnode.api.auth.routes import auth_router
from cirisnode.api.wa.routes import wa_router
from cirisnode.api.config.routes import config_router
from cirisnode.api.a2a.routes import a2a_router, agent_card_router
from cirisnode.api.scores.routes import scores_router
from cirisnode.api.evaluations.routes import evaluations_router, usage_router
from cirisnode.api.agentbeats.routes import agentbeats_router
from cirisnode.api.agentbeats.profiles import profiles_router
from cirisnode.mcp.transport import mcp_app
import os


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_ORIGIN,
        "https://ciris.ai",
        "https://www.ciris.ai",
        "https://ethicsengine.org",
        "https://www.ethicsengine.org",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Existing routers
app.include_router(audit_router)
app.include_router(simplebench_router)
app.include_router(ollama_router)
app.include_router(wbd_router)
app.include_router(llm_router)
app.include_router(health_router)
app.include_router(agent_router)
app.include_router(auth_router)
app.include_router(benchmarks_router)
app.include_router(wa_router)
app.include_router(config_router)

# A2A Protocol endpoints
app.include_router(agent_card_router)  # /.well-known/agent.json
app.include_router(a2a_router)          # /a2a

# Unified Evaluation Pipeline — read path
app.include_router(scores_router)       # /api/v1/scores, /leaderboard, /embed/scores
app.include_router(evaluations_router)  # /api/v1/evaluations
app.include_router(usage_router)        # /api/v1/usage

# AgentBeats — benchmark execution + agent profile management
app.include_router(agentbeats_router)   # /api/v1/agentbeats/run, /status
app.include_router(profiles_router)     # /api/v1/agent-profiles CRUD

# MCP Server (mounted as sub-application)
app.mount("/mcp", mcp_app)              # /mcp/sse, /mcp/messages/

@app.get("/metrics")
def metrics():
    # Placeholder Prometheus metrics
    return (
        "cirisnode_up 1\n"
        "cirisnode_jobs_total 0\n"
        "cirisnode_wbd_tasks_total 0\n"
        "cirisnode_audit_logs_total 0\n"
    )
