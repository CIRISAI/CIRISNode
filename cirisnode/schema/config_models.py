from pydantic import BaseModel, HttpUrl, field_validator
from typing import Optional

class LLMConfigV1(BaseModel):
    api_base: Optional[HttpUrl] = None
    model_name: Optional[str] = None

    @field_validator('api_base')
    def no_trailing_slash(cls, v):
        if v and str(v).endswith('/'):
            raise ValueError("api_base must not have a trailing slash")
        return v

    @field_validator('model_name')
    
    def model_required_if_api_base(cls, v, info):
        api_base = info.data.get('api_base') if hasattr(info, 'data') else None
        if api_base and not v:

            raise ValueError("model_name is required if api_base is set")
        return v

class CIRISConfigV1(BaseModel):
    version: int = 1
    llm: LLMConfigV1
