from fastapi import APIRouter, Depends
from cirisnode.dao.config_dao import get_config, ConfigDAO
from cirisnode.database import get_db
from cirisnode.schema.config_models import CIRISConfigV1
from cirisnode.utils.rbac import require_role

config_router = APIRouter(prefix="/api/v1/config", tags=["config"])

@config_router.get("", dependencies=[Depends(require_role(["admin", "wise_authority"]))])
def read_config(config: CIRISConfigV1 = Depends(get_config)):
    return config.model_dump()

@config_router.post("", dependencies=[Depends(require_role(["admin"]))])
def update_config(new_config: CIRISConfigV1, db=Depends(get_db)):
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    dao = ConfigDAO(conn)
    dao.save_config(new_config)
    return {"status": "updated", "version": new_config.version}
