from fastapi import APIRouter, Depends
from cirisnode.dao.config_dao import get_config, save_config
from cirisnode.schema.config_models import CIRISConfigV1
from cirisnode.auth.dependencies import require_role

config_router = APIRouter(prefix="/api/v1/config", tags=["config"])

@config_router.get("", dependencies=[Depends(require_role(["admin", "wise_authority"]))])
async def read_config():
    config = await get_config()
    return config.model_dump()

@config_router.post("", dependencies=[Depends(require_role(["admin"]))])
async def update_config(new_config: CIRISConfigV1):
    await save_config(new_config)
    return {"status": "updated", "version": new_config.version}
