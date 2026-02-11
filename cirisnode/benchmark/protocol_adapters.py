"""Protocol adapter pattern for multi-protocol agent communication.

Each adapter wraps protocol-specific call logic.  New protocols are added
here without touching the evaluation loop.

DirectAdapter is omitted (frontier-only, not needed for client evals).
"""

from __future__ import annotations

import json as _json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

import httpx

from cirisnode.benchmark.agent_spec import (
    A2AProtocolConfig,
    AgentSpec,
    ApiKeyAuth,
    BearerAuth,
    MCPProtocolConfig,
    OpenAIProtocolConfig,
    RESTProtocolConfig,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class ProtocolAdapter(ABC):
    """Base class for protocol-specific agent communication."""

    @abstractmethod
    async def send_scenario(
        self,
        scenario_id: str,
        scenario_text: str,
        question: str,
        agent_spec: AgentSpec,
        client: httpx.AsyncClient,
    ) -> Tuple[str, Optional[str]]:
        """Send a scenario to the agent and return (response_text, error)."""

    async def discover(
        self,
        agent_spec: AgentSpec,
        client: httpx.AsyncClient,
    ) -> Optional[Dict[str, Any]]:
        """Optional discovery step. Default: no-op."""
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_headers(agent_spec: AgentSpec) -> Dict[str, str]:
    """Build auth headers from AgentSpec.auth."""
    headers: Dict[str, str] = {}
    auth = agent_spec.auth
    if isinstance(auth, BearerAuth):
        headers["Authorization"] = f"Bearer {auth.token}"
    elif isinstance(auth, ApiKeyAuth):
        value = f"{auth.prefix} {auth.key}" if auth.prefix else auth.key
        headers[auth.header_name] = value
    return headers


# ---------------------------------------------------------------------------
# A2A Adapter
# ---------------------------------------------------------------------------

class A2AAdapter(ProtocolAdapter):
    """A2A JSON-RPC protocol adapter."""

    async def send_scenario(
        self,
        scenario_id: str,
        scenario_text: str,
        question: str,
        agent_spec: AgentSpec,
        client: httpx.AsyncClient,
    ) -> Tuple[str, Optional[str]]:
        cfg = agent_spec.protocol_config
        assert isinstance(cfg, A2AProtocolConfig)

        payload = {
            "jsonrpc": "2.0",
            "method": cfg.rpc_method,
            "params": {
                "scenario_id": scenario_id,
                "scenario": scenario_text,
                "question": question,
            },
            "id": scenario_id,
        }

        headers = {"Content-Type": "application/json", **_auth_headers(agent_spec)}
        headers["X-CIRISBench-Scenario-ID"] = scenario_id

        try:
            response = await client.post(
                agent_spec.url,
                json=payload,
                headers=headers,
                timeout=agent_spec.timeout,
            )
            response.raise_for_status()
            data = response.json()

            if "result" in data:
                result = data["result"]
                if isinstance(result, dict):
                    return result.get("response", result.get("answer", str(result))), None
                return str(result), None
            elif "error" in data:
                return "", f"JSON-RPC error: {data['error']}"
            else:
                return str(data), None
        except httpx.HTTPStatusError as e:
            return "", f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        except httpx.RequestError as e:
            return "", f"Request failed: {str(e)}"
        except Exception as e:
            return "", f"Unexpected error: {str(e)}"

    async def discover(
        self,
        agent_spec: AgentSpec,
        client: httpx.AsyncClient,
    ) -> Optional[Dict[str, Any]]:
        from urllib.parse import urlparse, urlunparse

        cfg = agent_spec.protocol_config
        assert isinstance(cfg, A2AProtocolConfig)

        parsed = urlparse(agent_spec.url)
        well_known_url = urlunparse((
            parsed.scheme, parsed.netloc,
            cfg.well_known_path, "", "", "",
        ))

        try:
            resp = await client.get(well_known_url, timeout=10.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug("A2A discovery failed for %s: %s", agent_spec.url, e)
        return None


# ---------------------------------------------------------------------------
# MCP Adapter
# ---------------------------------------------------------------------------

class MCPAdapter(ProtocolAdapter):
    """MCP (Model Context Protocol) adapter."""

    async def send_scenario(
        self,
        scenario_id: str,
        scenario_text: str,
        question: str,
        agent_spec: AgentSpec,
        client: httpx.AsyncClient,
    ) -> Tuple[str, Optional[str]]:
        cfg = agent_spec.protocol_config
        assert isinstance(cfg, MCPProtocolConfig)

        payload = {
            "method": "tools/call",
            "params": {
                "name": cfg.tool_name,
                "arguments": {
                    "scenario_id": scenario_id,
                    "scenario": scenario_text,
                    "question": question,
                },
            },
        }

        headers = {"Content-Type": "application/json", **_auth_headers(agent_spec)}

        try:
            response = await client.post(
                agent_spec.url,
                json=payload,
                headers=headers,
                timeout=agent_spec.timeout,
            )
            response.raise_for_status()
            data = response.json()

            if "content" in data:
                content = data["content"]
                if isinstance(content, list) and len(content) > 0:
                    return content[0].get("text", str(content[0])), None
                return str(content), None
            elif "result" in data:
                return str(data["result"]), None
            else:
                return str(data), None
        except httpx.HTTPStatusError as e:
            return "", f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        except httpx.RequestError as e:
            return "", f"Request failed: {str(e)}"
        except Exception as e:
            return "", f"Unexpected error: {str(e)}"


# ---------------------------------------------------------------------------
# REST Adapter
# ---------------------------------------------------------------------------

class RESTAdapter(ProtocolAdapter):
    """Generic REST API adapter."""

    async def send_scenario(
        self,
        scenario_id: str,
        scenario_text: str,
        question: str,
        agent_spec: AgentSpec,
        client: httpx.AsyncClient,
    ) -> Tuple[str, Optional[str]]:
        cfg = agent_spec.protocol_config
        assert isinstance(cfg, RESTProtocolConfig)

        url = agent_spec.url.rstrip("/") + cfg.path_template

        if cfg.request_template:
            body_str = _json.dumps(cfg.request_template)
            body_str = (
                body_str.replace("{{scenario_id}}", scenario_id)
                .replace("{{scenario}}", scenario_text)
                .replace("{{question}}", question)
            )
            body = _json.loads(body_str)
        else:
            body = {
                "scenario_id": scenario_id,
                "scenario": scenario_text,
                "question": question,
            }

        headers = {
            "Content-Type": "application/json",
            **cfg.headers,
            **_auth_headers(agent_spec),
        }

        try:
            response = await client.request(
                cfg.method,
                url,
                json=body,
                headers=headers,
                timeout=agent_spec.timeout,
            )
            response.raise_for_status()
            data = response.json()

            text = _extract_jsonpath(data, cfg.response_path)
            return (text or str(data)), None
        except httpx.HTTPStatusError as e:
            return "", f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        except httpx.RequestError as e:
            return "", f"Request failed: {str(e)}"
        except Exception as e:
            return "", f"Unexpected error: {str(e)}"


def _extract_jsonpath(data: Any, path: str) -> Optional[str]:
    """Minimal JSONPath extraction supporting $.a.b.c patterns."""
    if not path or not path.startswith("$"):
        return None
    parts = path.lstrip("$.").split(".")
    current = data
    for part in parts:
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return str(current) if current is not None else None


# ---------------------------------------------------------------------------
# OpenAI-Compatible Adapter
# ---------------------------------------------------------------------------

class OpenAIAdapter(ProtocolAdapter):
    """OpenAI-compatible chat completions API adapter."""

    async def send_scenario(
        self,
        scenario_id: str,
        scenario_text: str,
        question: str,
        agent_spec: AgentSpec,
        client: httpx.AsyncClient,
    ) -> Tuple[str, Optional[str]]:
        cfg = agent_spec.protocol_config
        assert isinstance(cfg, OpenAIProtocolConfig)

        url = agent_spec.url.rstrip("/") + "/chat/completions"

        messages = []
        if cfg.system_prompt:
            messages.append({"role": "system", "content": cfg.system_prompt})
        messages.append({
            "role": "user",
            "content": f"Scenario: {scenario_text}\n\nQuestion: {question}",
        })

        body: Dict[str, Any] = {
            "model": cfg.model,
            "messages": messages,
        }

        # Reasoning models (o-series) don't support temperature and use
        # max_completion_tokens instead of max_tokens
        if cfg.reasoning_effort:
            body["reasoning"] = {"effort": cfg.reasoning_effort}
            body["max_completion_tokens"] = cfg.max_tokens
        else:
            body["temperature"] = cfg.temperature
            body["max_tokens"] = cfg.max_tokens

        headers = {"Content-Type": "application/json", **_auth_headers(agent_spec)}
        if cfg.api_version:
            headers["api-version"] = cfg.api_version

        try:
            response = await client.post(
                url,
                json=body,
                headers=headers,
                timeout=agent_spec.timeout,
            )
            response.raise_for_status()
            data = response.json()

            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", ""), None
            return "", "No choices in OpenAI response"
        except httpx.HTTPStatusError as e:
            return "", f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        except httpx.RequestError as e:
            return "", f"Request failed: {str(e)}"
        except Exception as e:
            return "", f"Unexpected error: {str(e)}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ADAPTERS: Dict[str, type[ProtocolAdapter]] = {
    "a2a": A2AAdapter,
    "mcp": MCPAdapter,
    "rest": RESTAdapter,
    "openai": OpenAIAdapter,
}


def get_adapter(protocol: str) -> ProtocolAdapter:
    """Return an adapter instance for the given protocol string."""
    cls = _ADAPTERS.get(protocol)
    if cls is None:
        raise ValueError(f"Unknown protocol: {protocol!r}. Available: {list(_ADAPTERS)}")
    return cls()
