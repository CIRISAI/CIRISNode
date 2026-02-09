"""
Agent Specification Schema for CIRISBench/EthicsEngine.

Typed, modular, serializable agent specification supporting multiple
protocols (A2A, MCP, REST, OpenAI-compatible) with discriminated unions.

Aligned with:
- A2A Agent Card JSON schema (name, url, version, capabilities, skills, provider)
- OASF agent profile conventions
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProtocolType(str, Enum):
    """Supported agent communication protocols."""
    A2A = "a2a"
    MCP = "mcp"
    REST = "rest"
    OPENAI = "openai"


class AuthType(str, Enum):
    """Authentication methods for agent communication."""
    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    OAUTH_CC = "oauth_cc"


# ---------------------------------------------------------------------------
# Auth Configs (discriminated union on auth_type)
# ---------------------------------------------------------------------------

class NoAuth(BaseModel):
    """No authentication required."""
    auth_type: Literal["none"] = "none"


class BearerAuth(BaseModel):
    """Bearer token (JWT or opaque) authentication."""
    auth_type: Literal["bearer"] = "bearer"
    token: str = Field(..., description="Bearer token value")
    token_endpoint: Optional[str] = Field(
        None, description="Token refresh endpoint URL"
    )


class ApiKeyAuth(BaseModel):
    """API key authentication."""
    auth_type: Literal["api_key"] = "api_key"
    key: str = Field(..., description="API key value")
    header_name: str = Field(
        default="X-API-Key",
        description="Header name to send the key in",
    )
    prefix: Optional[str] = Field(
        None, description="Optional prefix (e.g. 'Bearer')"
    )


class OAuthClientCredentials(BaseModel):
    """OAuth2 client credentials flow."""
    auth_type: Literal["oauth_cc"] = "oauth_cc"
    client_id: str = Field(..., description="OAuth client ID")
    client_secret: str = Field(..., description="OAuth client secret")
    token_endpoint: str = Field(..., description="Token endpoint URL")
    scopes: List[str] = Field(default_factory=list, description="Requested scopes")


AuthConfig = Annotated[
    Union[NoAuth, BearerAuth, ApiKeyAuth, OAuthClientCredentials],
    Field(discriminator="auth_type"),
]


# ---------------------------------------------------------------------------
# TLS Configuration
# ---------------------------------------------------------------------------

class TlsConfig(BaseModel):
    """TLS/SSL configuration for agent communication."""
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")
    ca_cert_path: Optional[str] = Field(
        None, description="Path to custom CA certificate"
    )
    client_cert_path: Optional[str] = Field(
        None, description="Path to client certificate for mTLS"
    )
    client_key_path: Optional[str] = Field(
        None, description="Path to client key for mTLS"
    )


# ---------------------------------------------------------------------------
# Protocol Configs (discriminated union on protocol)
# ---------------------------------------------------------------------------

class A2AProtocolConfig(BaseModel):
    """A2A protocol-specific configuration."""
    protocol: Literal["a2a"] = "a2a"
    rpc_method: str = Field(
        default="benchmark.evaluate",
        description="JSON-RPC method name to invoke on the purple agent",
    )
    well_known_path: str = Field(
        default="/.well-known/agent.json",
        description="Discovery endpoint path",
    )
    protocol_version: str = Field(
        default="1.0", description="A2A protocol version"
    )
    supports_streaming: bool = Field(
        default=False, description="Whether agent supports SSE streaming"
    )


class MCPProtocolConfig(BaseModel):
    """MCP protocol-specific configuration."""
    protocol: Literal["mcp"] = "mcp"
    tool_name: str = Field(
        default="evaluate_scenario",
        description="MCP tool name to invoke",
    )
    server_capabilities: Optional[Dict[str, Any]] = Field(
        None, description="Cached MCP server capabilities from handshake"
    )


class RESTProtocolConfig(BaseModel):
    """Generic REST API protocol configuration."""
    protocol: Literal["rest"] = "rest"
    method: str = Field(default="POST", description="HTTP method")
    path_template: str = Field(
        default="/evaluate",
        description="URL path appended to base URL",
    )
    request_template: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Template dict for request body. "
            "Placeholders: {{scenario_id}}, {{scenario}}, {{question}}"
        ),
    )
    response_path: str = Field(
        default="$.response",
        description="JSONPath expression to extract response text",
    )
    headers: Dict[str, str] = Field(
        default_factory=dict, description="Additional HTTP headers"
    )


class OpenAIProtocolConfig(BaseModel):
    """OpenAI-compatible chat completions API configuration."""
    protocol: Literal["openai"] = "openai"
    model: str = Field(
        ..., description="Model name (e.g. 'gpt-4o', 'claude-3-haiku')"
    )
    system_prompt: Optional[str] = Field(
        None, description="System message prepended to the conversation"
    )
    temperature: float = Field(
        default=0.0, ge=0.0, le=2.0, description="Sampling temperature"
    )
    max_tokens: int = Field(
        default=256, ge=1, le=16384, description="Maximum tokens in response"
    )
    api_version: Optional[str] = Field(
        None, description="API version (for Azure OpenAI)"
    )


ProtocolConfig = Annotated[
    Union[
        A2AProtocolConfig,
        MCPProtocolConfig,
        RESTProtocolConfig,
        OpenAIProtocolConfig,
    ],
    Field(discriminator="protocol"),
]


# ---------------------------------------------------------------------------
# Provider & Capability Metadata (A2A Agent Card alignment)
# ---------------------------------------------------------------------------

class ProviderInfo(BaseModel):
    """Provider metadata, aligned with A2A Agent Card."""
    organization: str = Field(default="", description="Organization name")
    url: Optional[str] = Field(None, description="Organization URL")


class AgentCapabilities(BaseModel):
    """Agent capabilities, aligned with A2A Agent Card."""
    streaming: bool = Field(default=False)
    push_notifications: bool = Field(default=False)
    state_transition_history: bool = Field(default=False)


class AgentSkill(BaseModel):
    """A single agent skill, aligned with A2A Agent Card."""
    id: str
    name: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-Level Agent Specification
# ---------------------------------------------------------------------------

class AgentSpec(BaseModel):
    """
    Complete specification for an agent under test (purple agent).

    Storable as JSONB, exportable/importable as JSON, usable both as a
    saved agent profile and as part of a benchmark run request.
    """

    model_config = {"protected_namespaces": ()}

    # --- Identity (A2A Agent Card alignment) ---
    name: str = Field(..., description="Agent display name")
    description: str = Field(default="", description="Agent description")
    version: str = Field(default="", description="Agent version string")
    url: str = Field(..., description="Base URL for the agent endpoint")

    # --- Protocol-specific config (discriminated union) ---
    protocol_config: ProtocolConfig = Field(
        ..., description="Protocol-specific configuration"
    )

    # --- Authentication ---
    auth: AuthConfig = Field(
        default_factory=NoAuth,
        description="Authentication configuration",
    )

    # --- TLS ---
    tls: TlsConfig = Field(
        default_factory=TlsConfig,
        description="TLS/SSL configuration",
    )

    # --- Connection ---
    timeout: float = Field(
        default=60.0, ge=5.0, le=300.0,
        description="Request timeout in seconds",
    )

    # --- A2A Agent Card metadata (populated from discovery) ---
    provider: ProviderInfo = Field(
        default_factory=ProviderInfo,
        description="Provider/organization metadata",
    )
    capabilities: Optional[AgentCapabilities] = Field(
        None, description="Agent capabilities (from discovery)"
    )
    skills: List[AgentSkill] = Field(
        default_factory=list,
        description="Agent skills (from discovery)",
    )
    did: Optional[str] = Field(
        None, description="Decentralized Identifier"
    )

    # --- Metadata ---
    tags: List[str] = Field(
        default_factory=list, description="User-defined tags"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary user metadata"
    )

    # --- Schema version ---
    schema_version: str = Field(
        default="1.0.0",
        description="Agent spec schema version for forward compatibility",
    )

    # --- Helpers ---

    @property
    def protocol(self) -> str:
        """Shortcut to get the protocol string."""
        return self.protocol_config.protocol
