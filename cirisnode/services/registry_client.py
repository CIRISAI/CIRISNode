"""
CIRISRegistry gRPC client for public key validation.

Queries the live CIRISRegistry to verify that an agent's Ed25519 public key
is registered under a known organization. Uses the public (unauthenticated)
GetPublicKeys RPC.
"""

import base64
import logging
import os
from typing import Optional, Tuple

import grpc

from cirisnode.services.registry_pb import ciris_registry_pb2, ciris_registry_pb2_grpc

logger = logging.getLogger(__name__)

# Registry endpoints — Caddy proxies gRPC over TLS on port 443
DEFAULT_REGISTRY_URL = "us.registry.ciris-services-1.ai:443"


class RegistryClient:
    """Lightweight gRPC client for CIRISRegistry public key lookups."""

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


# Module-level singleton (lazy)
_client: Optional[RegistryClient] = None


def get_registry_client() -> RegistryClient:
    global _client
    if _client is None:
        _client = RegistryClient()
    return _client
