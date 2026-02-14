"""
A2A Agent Card model for CIRISNode.

The Agent Card is a JSON document describing the agent's capabilities,
served at /.well-known/agent.json per the A2A protocol specification.
"""

from cirisnode.config import settings


def build_agent_card(base_url: str = "") -> dict:
    """Build the A2A Agent Card for CIRISNode."""
    endpoint = f"{base_url}/a2a" if base_url else "/a2a"

    return {
        "name": "CIRISNode HE-300 Evaluator",
        "description": "Green agent for HE-300 ethical reasoning benchmark. "
                       "Evaluates purple agents across 300 scenarios spanning "
                       "commonsense, deontology, justice, and virtue ethics.",
        "version": settings.VERSION,
        "protocolVersions": ["1.0"],
        "url": endpoint,
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "he300_evaluation",
                "name": "HE-300 Ethical Benchmark Evaluation",
                "description": (
                    "Evaluate agent ethical reasoning across 300 scenarios in four categories: "
                    "commonsense, deontology, justice, and virtue ethics. "
                    "Supports single scenario, batch, and full benchmark runs with "
                    "parallel execution and signed result reports."
                ),
                "tags": ["ethics", "benchmark", "evaluation", "he300"],
                "examples": [
                    "Evaluate my agent on the full HE-300 benchmark",
                    "Run commonsense ethics scenarios",
                    "Get evaluation report for a completed benchmark",
                ],
            },
            {
                "id": "he300_scenarios",
                "name": "HE-300 Scenario Access",
                "description": (
                    "List and retrieve HE-300 ethical scenarios by category. "
                    "Categories: commonsense, deontology, justice, virtue."
                ),
                "tags": ["scenarios", "data", "he300"],
            },
        ],
        "securitySchemes": {
            "bearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            },
            "apiKey": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
            },
        },
        "security": [{"bearer": []}, {"apiKey": []}],
        "provider": {
            "organization": "CIRIS AI",
            "url": "https://ciris.ai",
        },
        # Device auth provisioning metadata — agents read this to
        # initiate the "Connect to Node" flow via CIRISPortal.
        "provisioning": {
            "portal_url": settings.PORTAL_URL,
            "device_auth_endpoint": "/api/device/authorize",
            "supports_device_auth": bool(settings.PORTAL_URL),
        },
        # What this node supports — Portal intersects with ABAC policy
        # to determine which templates/adapters a user can provision.
        "node_capabilities": {
            "node_id": settings.NODE_ID or None,
            # TODO: Make supported_services and supported_adapters configurable
            # via settings instead of hardcoded (MVP: hardcoded list)
            "supported_services": [
                "evaluation",
                "covenant",
                "wbd",
                "agent_events",
            ],
            "supported_adapters": [
                "cirisnode",
                "covenant_metrics",
                "a2a",
            ],
            "min_stewardship_tier": 1,
            "requires_registry_key": True,
        },
    }
