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


async def check_domain_supported(domain_hint: str | None) -> None:
    """Raise 403 if domain_hint is not supported by this node.

    Domain routing logic:
    - If domain_hint is None or empty: always accepted (general deferral)
    - If domain_hint is "GENERAL": always accepted
    - If domain_hint is a specialized domain (MEDICAL, FINANCIAL, etc.):
      - Accept if node's supported_domains includes this domain
      - Reject otherwise

    Empty supported_domains means the node only handles general deferrals.
    """
    # General deferrals (no domain_hint) are always accepted
    if not domain_hint or domain_hint == "GENERAL":
        return

    config = await get_config()

    # If node has no specialized domains configured, reject specialized deferrals
    if not config.supported_domains:
        logger.warning(
            "Domain %s rejected — node only handles general deferrals (no supported_domains configured)",
            domain_hint,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "domain_not_supported",
                "domain": domain_hint,
                "message": f"This node does not handle {domain_hint} deferrals. It only accepts general deferrals.",
            },
        )

    # Check if the domain is in the node's supported list
    if domain_hint not in config.supported_domains:
        logger.warning(
            "Domain %s rejected — not in supported list: %s",
            domain_hint,
            config.supported_domains,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "domain_not_supported",
                "domain": domain_hint,
                "supported_domains": config.supported_domains,
                "message": f"This node does not handle {domain_hint} deferrals.",
            },
        )
