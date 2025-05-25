from fastapi import APIRouter, HTTPException
import httpx
import os

ollama_router = APIRouter(tags=["ollama"])

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

@ollama_router.get("/api/v1/ollama-models")
async def get_ollama_models():
    """
    Fetch installed Ollama models and return simplified list
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=10)
            response.raise_for_status()
            data = response.json()
            return {"models": [model["name"] for model in data.get("models", [])]}
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama service unavailable")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
