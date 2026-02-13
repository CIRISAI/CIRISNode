"""
CIRISRegistry gRPC client for public key validation and agent metadata lookup.

Queries the live CIRISRegistry to:
- Verify agent Ed25519 public keys (unauthenticated GetPublicKeys RPC)
- Fetch full agent metadata (authenticated LookupAgent RPC with service JWT)
"""

import base64
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import grpc
import jwt

from cirisnode.services.registry_pb import ciris_registry_pb2, ciris_registry_pb2_grpc

logger = logging.getLogger(__name__)

# Registry endpoints — Caddy proxies gRPC over TLS on port 443
DEFAULT_REGISTRY_URL = "us.registry.ciris-services-1.ai:443"


class RegistryClient:
    """gRPC client for CIRISRegistry public key lookups and agent metadata."""

    def __init__(self, registry_url: Optional[str] = None) -> None:
        self._url = registry_url or os.getenv("CIRIS_REGISTRY_URL", DEFAULT_REGISTRY_URL)
        self._channel: Optional[grpc.Channel] = None
        self._stub: Optional[ciris_registry_pb2_grpc.RegistryServiceStub] = None

    def _ensure_channel(self) -> ciris_registry_pb2_grpc.RegistryServiceStub:
        if self._stub is None:
            # Use TLS since Caddy terminates with Let's Encrypt certs
            credentials = grpc.ssl_channel_credentials()
            self._channel = grpc.secure_channel(self._url, credentials)
            self._stub = ciris_registry_pb2_grpc.RegistryServiceStub(self._channel)
            logger.info(f"RegistryClient connected to {self._url}")
        return self._stub

    def _registry_jwt(self) -> str:
        """Generate a short-lived service JWT for authenticated Registry calls."""
        from cirisnode.config import settings

        secret = settings.REGISTRY_JWT_SECRET
        if not secret:
            raise ValueError("REGISTRY_JWT_SECRET not configured — cannot authenticate with Registry")

        now = int(time.time())
        payload = {
            "sub": "cirisnode-service",
            "org_id": "ciris-internal",
            "role": 0,  # Role 0 = service (matches Registry auth middleware)
            "iat": now,
            "exp": now + 300,  # 5 minute expiry
        }
        return jwt.encode(payload, secret, algorithm="HS256")

    def close(self) -> None:
        if self._channel:
            self._channel.close()
            self._channel = None
            self._stub = None

    def get_public_key(
        self, org_id: str, key_id: str = ""
    ) -> Tuple[bool, Optional[bytes], Optional[str]]:
        """Look up an organization's Ed25519 public key from the registry.

        Args:
            org_id: Organization ID in the registry.
            key_id: Specific key ID (empty = active key).

        Returns:
            (found, ed25519_pubkey_bytes, key_status_name)
        """
        try:
            stub = self._ensure_channel()
            request = ciris_registry_pb2.GetPublicKeysRequest(
                org_id=org_id,
                key_id=key_id,
            )
            response = stub.GetPublicKeys(request, timeout=10)

            if not response.found:
                return False, None, None

            ed25519_bytes = response.public_keys.ed25519_public_key
            status_name = ciris_registry_pb2.KeyStatus.Name(response.status)
            return True, ed25519_bytes, status_name

        except grpc.RpcError as e:
            logger.warning(f"Registry GetPublicKeys failed: {e.code()} {e.details()}")
            return False, None, None
        except Exception as e:
            logger.warning(f"Registry GetPublicKeys error: {e}")
            return False, None, None

    def get_key_by_fingerprint(
        self, ed25519_fingerprint: str
    ) -> Tuple[bool, Optional[str], Optional[bytes], Optional[str]]:
        """Look up a key by its Ed25519 fingerprint (SHA-256 hex of public key).

        Args:
            ed25519_fingerprint: SHA-256 hex digest of the Ed25519 public key.

        Returns:
            (found, org_id, ed25519_pubkey_bytes, key_status_name)
        """
        try:
            stub = self._ensure_channel()
            request = ciris_registry_pb2.GetPublicKeysRequest(
                ed25519_fingerprint=ed25519_fingerprint,
            )
            response = stub.GetPublicKeys(request, timeout=10)

            if not response.found:
                return False, None, None, None

            ed25519_bytes = response.public_keys.ed25519_public_key
            status_name = ciris_registry_pb2.KeyStatus.Name(response.status)
            return True, response.org_id, ed25519_bytes, status_name

        except grpc.RpcError as e:
            logger.warning(f"Registry fingerprint lookup failed: {e.code()} {e.details()}")
            return False, None, None, None
        except Exception as e:
            logger.warning(f"Registry fingerprint lookup error: {e}")
            return False, None, None, None

    def verify_key_matches(
        self, org_id: str, key_id: str, claimed_pubkey_b64: str
    ) -> Tuple[bool, str]:
        """Verify a claimed public key matches what the registry has.

        Args:
            org_id: Organization ID.
            key_id: Key ID to look up.
            claimed_pubkey_b64: Base64-encoded Ed25519 public key the agent claims.

        Returns:
            (matches, reason_string)
        """
        found, registry_pubkey, status = self.get_public_key(org_id, key_id)

        if not found:
            return False, "key not found in registry"

        if status in ("KEY_REVOKED",):
            return False, f"key revoked in registry (status={status})"

        if status in ("KEY_PENDING",):
            return False, f"key not yet active in registry (status={status})"

        # Compare the Ed25519 public key bytes
        try:
            claimed_bytes = base64.b64decode(claimed_pubkey_b64)
        except Exception:
            return False, "invalid base64 in claimed key"

        if registry_pubkey == claimed_bytes:
            return True, f"verified (status={status})"
        else:
            return False, "public key mismatch — claimed key does not match registry"

    def lookup_agent_full(self, agent_hash_hex: str) -> Optional[Dict[str, Any]]:
        """Fetch full (non-redacted) agent metadata from Registry using service JWT.

        Args:
            agent_hash_hex: Hex-encoded agent hash (e.g. "afde5906...").

        Returns:
            Dict with full agent record fields, or None if not found / error.
        """
        try:
            stub = self._ensure_channel()
            token = self._registry_jwt()
            metadata = [("authorization", f"Bearer {token}")]

            agent_hash_bytes = bytes.fromhex(agent_hash_hex)
            request = ciris_registry_pb2.LookupAgentRequest(
                agent_hash=agent_hash_bytes,
            )
            response = stub.LookupAgent(request, timeout=10, metadata=metadata)

            if not response.found or not response.agent:
                return None

            agent = response.agent
            return {
                "agent_hash_hex": agent.agent_hash_hex,
                "agent_type": agent.agent_type,
                "version": {
                    "major": agent.version.major,
                    "minor": agent.version.minor,
                    "patch": agent.version.patch,
                } if agent.version else None,
                "status": agent.status,
                "registered_at": agent.registered_at,
                "identity_template": agent.identity_template,
                "base_capabilities": list(agent.base_capabilities),
                "max_autonomy_tier": agent.max_autonomy_tier,
                "permitted_actions": list(agent.permitted_actions),
                "approved_adapters": list(agent.approved_adapters),
                "stewardship_tier": agent.stewardship_tier,
                "org_id": agent.org_id,
                "template_hash": agent.template_hash.hex() if agent.template_hash else "",
                "source_repo": agent.source_repo,
                "source_commit": agent.source_commit,
            }

        except grpc.RpcError as e:
            logger.warning(f"Registry LookupAgent failed: {e.code()} {e.details()}")
            return None
        except ValueError as e:
            logger.warning(f"Registry LookupAgent auth error: {e}")
            return None
        except Exception as e:
            logger.warning(f"Registry LookupAgent error: {e}")
            return None


# Module-level singleton (lazy)
_client: Optional[RegistryClient] = None


def get_registry_client() -> RegistryClient:
    global _client
    if _client is None:
        _client = RegistryClient()
    return _client
