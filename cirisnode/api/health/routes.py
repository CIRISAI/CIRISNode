from pathlib import Path

from fastapi import APIRouter, Depends, Request
from datetime import datetime, timezone
from cirisnode.dao.config_dao import get_config
from cirisnode.schema.config_models import CIRISConfigV1

router = APIRouter(prefix="/api/v1/health", tags=["health"])

# Read build number once at import time
_BUILD_FILE = Path(__file__).resolve().parents[3] / "BUILD_NUMBER"
try:
    _BUILD_NUMBER = int(_BUILD_FILE.read_text().strip())
except Exception:
    _BUILD_NUMBER = 0

@router.get("")
def health_check(request: Request, config: CIRISConfigV1 = Depends(get_config)):
    return {
        "status": "ok",
        "version": config.version,
        "build": _BUILD_NUMBER,
        "pubkey": "dummy-pubkey",
        "message": "CIRISNode is healthy",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
