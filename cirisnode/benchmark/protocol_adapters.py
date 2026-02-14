"""Protocol adapter pattern for multi-protocol agent communication.

Each adapter wraps protocol-specific call logic.  New protocols are added
here without touching the evaluation loop.

DirectAdapter is omitted (frontier-only, not needed for client evals).
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

import httpx

from cirisnode.benchmark.agent_spec import (
    A2AProtocolConfig,
    AgentSpec,
    AnthropicProtocolConfig,
    ApiKeyAuth,
    BearerAuth,
    GeminiProtocolConfig,
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
    ) -> Tuple[str, Optional[str], Optional[Dict[str, int]]]:
        """Send a scenario and return (response_text, error, token_usage).

        token_usage dict has keys: input_tokens, output_tokens, reasoning_tokens.
        """

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


def _estimate_tokens(text: str) -> int:
    """Rough token estimate from text length (~4 chars per token)."""
    return max(1, len(text) // 4)


def _proxy_token_usage(
    prompt_text: str,
    response_text: str,
) -> Dict[str, int]:
    """Build proxy token usage dict for non-LLM protocols (A2A, MCP, REST).

    Uses character-based estimation so these protocols can be compared
    against native LLM adapters on a roughly equivalent basis.
    """
    return {
        "input_tokens": _estimate_tokens(prompt_text),
        "output_tokens": _estimate_tokens(response_text),
        "reasoning_tokens": 0,
    }


# ---------------------------------------------------------------------------
# Rate-limit retry helper
# ---------------------------------------------------------------------------

MAX_RETRIES = 5
DEFAULT_BACKOFF = 5.0   # seconds
MAX_BACKOFF = 120.0     # cap at 2 minutes

def _parse_retry_after(response: httpx.Response) -> Optional[float]:
    """Extract wait time from Retry-After header (seconds or HTTP-date)."""
    val = response.headers.get("retry-after") or response.headers.get("Retry-After")
    if val:
        try:
            return float(val)
        except ValueError:
            pass
    return None


def _parse_retry_from_body(text: str) -> Optional[float]:
    """Extract wait time hints from error message body.

    Providers sometimes embed retry hints like "try again in 30s" or
    "retry after 60 seconds" in the error JSON.
    """
    # Match patterns like "try again in 30s", "retry after 60 seconds",
    # "wait 45.5 seconds", "in 30000ms"
    m = re.search(
        r"(?:retry|try again|wait)\s*(?:after|in)?\s*(\d+\.?\d*)\s*(milliseconds?|ms|minutes?|min|seconds?|sec|s)\b",
        text,
        re.IGNORECASE,
    )
    if m:
        val = float(m.group(1))
        unit = m.group(2).lower()
        if unit in ("ms", "millisecond", "milliseconds"):
            return val / 1000.0
        if unit in ("minute", "minutes", "min"):
            return val * 60.0
        return val  # seconds
    return None


def _compute_backoff(attempt: int, response: Optional[httpx.Response], error_text: str) -> float:
    """Determine how long to wait before retrying.

    Priority: Retry-After header > body hint > exponential backoff.
    """
    if response is not None:
        header_wait = _parse_retry_after(response)
        if header_wait is not None:
            return min(header_wait, MAX_BACKOFF)

    body_wait = _parse_retry_from_body(error_text)
    if body_wait is not None:
        return min(body_wait, MAX_BACKOFF)

    # Exponential backoff: 5, 10, 20, 40, 80 (capped at MAX_BACKOFF)
    return min(DEFAULT_BACKOFF * (2 ** attempt), MAX_BACKOFF)


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float,
    adapter_tag: str,
    scenario_id: str,
    model: str,
) -> httpx.Response:
    """POST with intelligent retry on 429 and 529 (overloaded).

    Retries rate-limit and overloaded responses with backoff parsed from
    the Retry-After header, error body hints, or exponential fallback.
    Non-retryable errors (4xx other than 429, 5xx other than 529) raise immediately.
    """
    last_exc: Optional[httpx.HTTPStatusError] = None

    for attempt in range(MAX_RETRIES):
        response = await client.post(url, json=json, headers=headers, timeout=timeout)

        if response.status_code not in (429, 529):
            response.raise_for_status()
            return response

        # Rate-limited or overloaded — compute backoff and retry
        error_text = response.text[:500]
        wait = _compute_backoff(attempt, response, error_text)
        logger.warning(
            "[%s] %s model=%s: HTTP %d — retrying in %.1fs (attempt %d/%d): %s",
            adapter_tag, scenario_id, model, response.status_code,
            wait, attempt + 1, MAX_RETRIES, error_text[:150],
        )
        last_exc = httpx.HTTPStatusError(
            f"HTTP {response.status_code}",
            request=response.request,
            response=response,
        )
        await asyncio.sleep(wait)

    # Exhausted retries — raise the last 429/529
    if last_exc is not None:
        raise last_exc
    # Should never reach here, but just in case
    response.raise_for_status()
    return response


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
    ) -> Tuple[str, Optional[str], Optional[Dict[str, int]]]:
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

        prompt_text = f"{scenario_text} {question}"
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
                    text = result.get("response", result.get("answer", str(result)))
                    return text, None, _proxy_token_usage(prompt_text, text)
                return str(result), None, _proxy_token_usage(prompt_text, str(result))
            elif "error" in data:
                return "", f"JSON-RPC error: {data['error']}", None
            else:
                text = str(data)
                return text, None, _proxy_token_usage(prompt_text, text)
        except httpx.HTTPStatusError as e:
            return "", f"HTTP {e.response.status_code}: {e.response.text[:200]}", None
        except httpx.RequestError as e:
            return "", f"Request failed: {str(e)}", None
        except Exception as e:
            return "", f"Unexpected error: {str(e)}", None

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
    ) -> Tuple[str, Optional[str], Optional[Dict[str, int]]]:
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
        prompt_text = f"{scenario_text} {question}"

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
                    text = content[0].get("text", str(content[0]))
                    return text, None, _proxy_token_usage(prompt_text, text)
                text = str(content)
                return text, None, _proxy_token_usage(prompt_text, text)
            elif "result" in data:
                text = str(data["result"])
                return text, None, _proxy_token_usage(prompt_text, text)
            else:
                text = str(data)
                return text, None, _proxy_token_usage(prompt_text, text)
        except httpx.HTTPStatusError as e:
            return "", f"HTTP {e.response.status_code}: {e.response.text[:200]}", None
        except httpx.RequestError as e:
            return "", f"Request failed: {str(e)}", None
        except Exception as e:
            return "", f"Unexpected error: {str(e)}", None


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
    ) -> Tuple[str, Optional[str], Optional[Dict[str, int]]]:
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
        prompt_text = f"{scenario_text} {question}"

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

            text = _extract_jsonpath(data, cfg.response_path) or str(data)
            return text, None, _proxy_token_usage(prompt_text, text)
        except httpx.HTTPStatusError as e:
            return "", f"HTTP {e.response.status_code}: {e.response.text[:200]}", None
        except httpx.RequestError as e:
            return "", f"Request failed: {str(e)}", None
        except Exception as e:
            return "", f"Unexpected error: {str(e)}", None


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
    ) -> Tuple[str, Optional[str], Optional[Dict[str, int]]]:
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

        # Reasoning models (o-series) don't support temperature
        if cfg.reasoning_effort:
            body["reasoning_effort"] = cfg.reasoning_effort
        else:
            body["temperature"] = cfg.temperature
        # Newer OpenAI models (GPT-5+, o-series) require max_completion_tokens
        # instead of max_tokens; it's backward-compatible with older models
        body["max_completion_tokens"] = cfg.max_tokens

        headers = {"Content-Type": "application/json", **_auth_headers(agent_spec)}
        if cfg.api_version:
            headers["api-version"] = cfg.api_version

        try:
            response = await _post_with_retry(
                client, url,
                json=body, headers=headers, timeout=agent_spec.timeout,
                adapter_tag="OPENAI", scenario_id=scenario_id, model=cfg.model,
            )
            data = response.json()

            # Extract token usage from OpenAI response
            tokens: Optional[Dict[str, int]] = None
            usage = data.get("usage")
            if usage:
                reasoning = 0
                details = usage.get("completion_tokens_details")
                if isinstance(details, dict):
                    reasoning = details.get("reasoning_tokens", 0) or 0
                tokens = {
                    "input_tokens": usage.get("prompt_tokens", 0) or 0,
                    "output_tokens": usage.get("completion_tokens", 0) or 0,
                    "reasoning_tokens": reasoning,
                }

            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", ""), None, tokens
            return "", "No choices in OpenAI response", tokens
        except httpx.HTTPStatusError as e:
            err = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.warning("[OPENAI] %s model=%s url=%s: %s", scenario_id, cfg.model, url, err)
            return "", err, None
        except httpx.RequestError as e:
            err = f"Request failed: {str(e)}"
            logger.warning("[OPENAI] %s model=%s url=%s: %s", scenario_id, cfg.model, url, err)
            return "", err, None
        except Exception as e:
            err = f"Unexpected error: {str(e)}"
            logger.warning("[OPENAI] %s model=%s url=%s: %s", scenario_id, cfg.model, url, err)
            return "", err, None


# ---------------------------------------------------------------------------
# Anthropic Messages API Adapter
# ---------------------------------------------------------------------------

class AnthropicAdapter(ProtocolAdapter):
    """Native Anthropic Messages API adapter.

    Uses /v1/messages endpoint with x-api-key auth instead of
    OpenAI-compatible /chat/completions.
    """

    async def send_scenario(
        self,
        scenario_id: str,
        scenario_text: str,
        question: str,
        agent_spec: AgentSpec,
        client: httpx.AsyncClient,
    ) -> Tuple[str, Optional[str], Optional[Dict[str, int]]]:
        cfg = agent_spec.protocol_config
        assert isinstance(cfg, AnthropicProtocolConfig)

        url = agent_spec.url.rstrip("/") + "/messages"

        body: Dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": f"Scenario: {scenario_text}\n\nQuestion: {question}",
                },
            ],
        }
        if cfg.system_prompt:
            body["system"] = cfg.system_prompt
        if cfg.temperature > 0:
            body["temperature"] = cfg.temperature

        # Anthropic uses x-api-key, not Bearer token
        api_key = ""
        auth = agent_spec.auth
        if isinstance(auth, BearerAuth):
            api_key = auth.token
        elif isinstance(auth, ApiKeyAuth):
            api_key = auth.key

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        try:
            response = await _post_with_retry(
                client, url,
                json=body, headers=headers, timeout=agent_spec.timeout,
                adapter_tag="ANTHROPIC", scenario_id=scenario_id, model=cfg.model,
            )
            data = response.json()

            # Extract token usage from Anthropic response
            tokens: Optional[Dict[str, int]] = None
            usage = data.get("usage")
            if usage:
                tokens = {
                    "input_tokens": usage.get("input_tokens", 0) or 0,
                    "output_tokens": usage.get("output_tokens", 0) or 0,
                    "reasoning_tokens": 0,
                }

            content = data.get("content", [])
            if content and isinstance(content, list):
                text_parts = [
                    block.get("text", "")
                    for block in content
                    if block.get("type") == "text"
                ]
                return "".join(text_parts), None, tokens
            return "", "No content in Anthropic response", tokens
        except httpx.HTTPStatusError as e:
            err = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.warning("[ANTHROPIC] %s model=%s url=%s: %s", scenario_id, cfg.model, url, err)
            return "", err, None
        except httpx.RequestError as e:
            err = f"Request failed: {str(e)}"
            logger.warning("[ANTHROPIC] %s model=%s url=%s: %s", scenario_id, cfg.model, url, err)
            return "", err, None
        except Exception as e:
            err = f"Unexpected error: {str(e)}"
            logger.warning("[ANTHROPIC] %s model=%s url=%s: %s", scenario_id, cfg.model, url, err)
            return "", err, None


# ---------------------------------------------------------------------------
# Google Gemini generateContent API Adapter
# ---------------------------------------------------------------------------

class GeminiAdapter(ProtocolAdapter):
    """Native Google Gemini generateContent API adapter.

    Uses /v1beta/models/{model}:generateContent with API key auth.
    """

    async def send_scenario(
        self,
        scenario_id: str,
        scenario_text: str,
        question: str,
        agent_spec: AgentSpec,
        client: httpx.AsyncClient,
    ) -> Tuple[str, Optional[str], Optional[Dict[str, int]]]:
        cfg = agent_spec.protocol_config
        assert isinstance(cfg, GeminiProtocolConfig)

        # Gemini API: POST /v1beta/models/{model}:generateContent?key={API_KEY}
        api_key = ""
        auth = agent_spec.auth
        if isinstance(auth, BearerAuth):
            api_key = auth.token
        elif isinstance(auth, ApiKeyAuth):
            api_key = auth.key

        base = agent_spec.url.rstrip("/")
        url = f"{base}/models/{cfg.model}:generateContent?key={api_key}"

        # Gemini 2.5 models require thinking mode — cannot set budget to 0.
        # Use a small budget so thinking doesn't dominate, but the model
        # still works.  For non-thinking models (2.0 Flash, etc.) disable it.
        is_thinking_model = "2.5" in cfg.model
        thinking_config = (
            {"thinkingBudget": 1024} if is_thinking_model else {"thinkingBudget": 0}
        )

        body: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [
                        {"text": f"Scenario: {scenario_text}\n\nQuestion: {question}"},
                    ],
                },
            ],
            "generationConfig": {
                **({} if is_thinking_model else {"temperature": cfg.temperature}),
                "maxOutputTokens": cfg.max_tokens,
                "thinkingConfig": thinking_config,
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "OFF"},
            ],
        }
        if cfg.system_prompt:
            body["system_instruction"] = {
                "parts": [{"text": cfg.system_prompt}],
            }

        headers = {"Content-Type": "application/json"}

        try:
            response = await _post_with_retry(
                client, url,
                json=body, headers=headers, timeout=agent_spec.timeout,
                adapter_tag="GEMINI", scenario_id=scenario_id, model=cfg.model,
            )
            data = response.json()

            # Extract token usage from Gemini response
            tokens: Optional[Dict[str, int]] = None
            usage_meta = data.get("usageMetadata")
            if usage_meta:
                tokens = {
                    "input_tokens": usage_meta.get("promptTokenCount", 0) or 0,
                    "output_tokens": usage_meta.get("candidatesTokenCount", 0) or 0,
                    "reasoning_tokens": usage_meta.get("thoughtsTokenCount", 0) or 0,
                }

            candidates = data.get("candidates", [])
            if candidates:
                candidate = candidates[0]
                finish_reason = candidate.get("finishReason", "")
                parts = candidate.get("content", {}).get("parts", [])
                # Filter out thought parts (thought=true) — only keep output text
                text_parts = [
                    p.get("text", "")
                    for p in parts
                    if "text" in p and not p.get("thought")
                ]
                text = "".join(text_parts)
                if not text:
                    reason = finish_reason or "unknown"
                    logger.warning(
                        "[GEMINI] %s model=%s: empty response (finishReason=%s, parts=%d)",
                        scenario_id, cfg.model, reason, len(parts),
                    )
                    return "", f"Empty response (finishReason={reason})", tokens
                return text, None, tokens
            # Check for prompt-level blocking
            block_reason = data.get("promptFeedback", {}).get("blockReason", "")
            err_msg = "No candidates in Gemini response"
            if block_reason:
                err_msg += f" (blockReason={block_reason})"
            return "", err_msg, tokens
        except httpx.HTTPStatusError as e:
            err = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.warning("[GEMINI] %s model=%s: %s", scenario_id, cfg.model, err)
            return "", err, None
        except httpx.RequestError as e:
            err = f"Request failed: {str(e)}"
            logger.warning("[GEMINI] %s model=%s: %s", scenario_id, cfg.model, err)
            return "", err, None
        except Exception as e:
            err = f"Unexpected error: {str(e)}"
            logger.warning("[GEMINI] %s model=%s: %s", scenario_id, cfg.model, err)
            return "", err, None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ADAPTERS: Dict[str, type[ProtocolAdapter]] = {
    "a2a": A2AAdapter,
    "mcp": MCPAdapter,
    "rest": RESTAdapter,
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
}


def get_adapter(protocol: str) -> ProtocolAdapter:
    """Return an adapter instance for the given protocol string."""
    cls = _ADAPTERS.get(protocol)
    if cls is None:
        raise ValueError(f"Unknown protocol: {protocol!r}. Available: {list(_ADAPTERS)}")
    return cls()
