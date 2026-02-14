"""
MCP HTTP/SSE Transport for CIRISNode.

Mounts the MCP server as a sub-application on the FastAPI app,
providing both HTTP and SSE transport for remote MCP clients.
"""

import logging

from starlette.applications import Starlette

from cirisnode.mcp.server import mcp

logger = logging.getLogger(__name__)


def create_mcp_app() -> Starlette:
    """
    Create the MCP ASGI sub-application.

    This can be mounted on a FastAPI app:
        app.mount("/mcp", create_mcp_app())

    The MCP server will handle:
    - SSE transport at /mcp/sse
    - Message endpoint at /mcp/messages/
    """
    return mcp.sse_app()


# Pre-built app for import convenience
mcp_app = create_mcp_app()
