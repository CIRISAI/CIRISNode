"""Dual authentication for A2A and MCP endpoints.

Delegates to the centralized auth module. This file is kept for
backward compatibility with imports from existing code.
"""

from cirisnode.auth.dependencies import require_auth

# Backward-compatible alias
validate_a2a_auth = require_auth
