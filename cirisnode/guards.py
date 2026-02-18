"""Node-level access guards: org allowlist and feature flags.

These guards read from the singleton config table (managed via /api/v1/config)
and enforce org-level access control and feature gating across all endpoints.
"""

import logging
from fastapi import HTTPException, status

from cirisnode.dao.config_dao import get_config

logger = logging.getLogger(__name__)


async def check_org_allowed(org_id: str | None) -> None:
    """Raise 403 if org_id is not in this node's allowed org list.

    If allowed_org_ids is empty, all orgs are permitted (open node).
    If org_id is None or empty, access is denied when an allowlist is set.
    """
    config = await get_config()
    if not config.allowed_org_ids:
        return  # Open node — no restrictions

    if not org_id or org_id not in config.allowed_org_ids:
        logger.warning(
            "Org %s denied — not in allowed list: %s",
            org_id,
            config.allowed_org_ids,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This node does not service your organization. Contact sales@ciris.ai for access.",
        )


async def require_feature(feature_name: str) -> None:
    """Raise 403 if the named feature is disabled on this node.

    Valid feature names: wbd_routing, benchmarking, frontier_sweep
    """
    config = await get_config()
    enabled = getattr(config.features, feature_name, None)
    if enabled is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unknown feature flag: {feature_name}",
        )
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Feature '{feature_name}' is not enabled on this node.",
        )
