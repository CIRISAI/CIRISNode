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

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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

@app.get("/metrics")
def metrics():
    # Placeholder Prometheus metrics
    return (
        "cirisnode_up 1\n"
        "cirisnode_jobs_total 0\n"
        "cirisnode_wbd_tasks_total 0\n"
        "cirisnode_audit_logs_total 0\n"
    )
