"""Unified authentication module for CIRISNode.

Consolidates JWT validation, role-based access control, agent token auth,
and password hashing into a single module. All route files should import
auth dependencies from here rather than implementing their own.
"""

from cirisnode.auth.dependencies import (
    decode_jwt,
    get_current_user,
    get_current_role,
    require_role,
    require_auth,
    require_agent_token,
    optional_auth,
    get_actor_from_token,
)
from cirisnode.auth.passwords import hash_password, verify_password

__all__ = [
    "decode_jwt",
    "get_current_user",
    "get_current_role",
    "require_role",
    "require_auth",
    "require_agent_token",
    "optional_auth",
    "get_actor_from_token",
    "hash_password",
    "verify_password",
]
