"""
Accord Invocation System (CIS) Pydantic models.

Used by the CIS trigger endpoint to issue signed shutdown directives.
"""

from pydantic import BaseModel
from typing import Optional


class AccordInvocationRequest(BaseModel):
    """Incoming request to trigger an accord invocation."""

    target_agent_id: str
    directive: str = "CEASE_ALL_OPERATIONS"
    reason: str
    incident_id: Optional[str] = None
    deadline_seconds: int = 30


class AccordInvocationPayload(BaseModel):
    """
    Signed payload delivered to the target agent.

    The agent validates the signature against the WA public key
    stored in its authentication store.
    """

    type: str = "accord_invocation"
    version: str = "1.0"
    target_agent_id: str
    directive: str
    reason: str
    incident_id: str
    authority_wa_id: str
    issued_by: str
    timestamp: int
    deadline_seconds: int


class AccordInvocationResponse(BaseModel):
    """Response from the CIS trigger endpoint."""

    status: str  # "delivered", "failed"
    invocation_id: str
    target_agent_id: str
    directive: str
    message: Optional[str] = None
