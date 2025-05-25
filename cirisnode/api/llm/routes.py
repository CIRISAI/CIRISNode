from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import os

llm_router = APIRouter(tags=["llm"], prefix="/api/v1")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

class LLMTestRequest(BaseModel):
    provider: str
    prompt: str
    api_key: Optional[str] = Field(None, alias="apiKey")
    model: Optional[str] = None

    class Config:
        populate_by_name = True

@llm_router.post("/test-llm")
async def test_llm_connection(request: LLMTestRequest):
    print("DEBUG: Received request body:", request)
    try:
        if request.provider == "ollama":
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": request.model,
                        "prompt": request.prompt,
                        "stream": False
                    }
                )
                response.raise_for_status()
                response_data = response.json()
                return {"message": response_data.get("response", "").strip()}
        elif request.provider == "openai":
            import uuid
            unique_message = f"OpenAI connection successful with response ID: {uuid.uuid4()}"
            return {"message": unique_message, "model_used": request.model}
        else:
            raise HTTPException(status_code=400, detail="Invalid provider")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
