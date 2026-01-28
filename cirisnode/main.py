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
from cirisnode.mcp.transport import mcp_app
import os

app = FastAPI()

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "https://node0.ciris.ai")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
