"""
Ed25519 signing utility with persistent WA key support.

Supports both:
- Ephemeral keys (backward compat, auto-generated if no config)
- Persistent WA keys (loaded from CIRISNODE_WA_PRIVATE_KEY config)
"""

import base64
import json
import logging
from typing import Dict, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = logging.getLogger(__name__)

# Lazy-loaded persistent WA key
_wa_private_key: Optional[ed25519.Ed25519PrivateKey] = None
_wa_key_loaded: bool = False

# Ephemeral key pair (backward compat — generated on first use)
_ephemeral_private_key: Optional[ed25519.Ed25519PrivateKey] = None
_ephemeral_public_key: Optional[ed25519.Ed25519PublicKey] = None


def _get_ephemeral_key() -> ed25519.Ed25519PrivateKey:
    """Get or generate the ephemeral key pair (backward compat)."""
    global _ephemeral_private_key, _ephemeral_public_key
    if _ephemeral_private_key is None:
        _ephemeral_private_key = ed25519.Ed25519PrivateKey.generate()
        _ephemeral_public_key = _ephemeral_private_key.public_key()
    return _ephemeral_private_key


def load_wa_key(private_key_b64: str) -> ed25519.Ed25519PrivateKey:
    """Load a persistent WA Ed25519 private key from base64-encoded 32-byte seed."""
    raw_bytes = base64.b64decode(private_key_b64)
    if len(raw_bytes) != 32:
        raise ValueError(f"WA private key must be 32 bytes, got {len(raw_bytes)}")
    return ed25519.Ed25519PrivateKey.from_private_bytes(raw_bytes)


def get_wa_private_key() -> Optional[ed25519.Ed25519PrivateKey]:
    """
    Get the persistent WA private key from config.

    Returns None if CIRISNODE_WA_PRIVATE_KEY is not set.
    """
    global _wa_private_key, _wa_key_loaded
    if _wa_key_loaded:
        return _wa_private_key

    _wa_key_loaded = True
    try:
        from cirisnode.config import settings
        if settings.CIRISNODE_WA_PRIVATE_KEY:
            _wa_private_key = load_wa_key(settings.CIRISNODE_WA_PRIVATE_KEY)
            logger.info(
                "wa_key_loaded key_id=%s",
                settings.CIRISNODE_WA_KEY_ID or "(no key_id)",
            )
        else:
            logger.info("wa_key_not_configured, using ephemeral key")
    except Exception as e:
        logger.error("Failed to load WA private key: %s", e)
        _wa_private_key = None

    return _wa_private_key


def get_wa_public_key_b64() -> str:
    """Get the WA public key as base64 string (raw 32 bytes)."""
    key = get_wa_private_key()
    if key is None:
        key = _get_ephemeral_key()
    pub = key.public_key()
    raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode()


def sign_accord_invocation(payload: dict, private_key: ed25519.Ed25519PrivateKey) -> str:
    """
    Sign an accord invocation payload with Ed25519.

    Uses canonical JSON (sorted keys, compact separators) for reproducibility.
    Returns hex-encoded signature.
    """
    message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(message)
    return signature.hex()


# --------------------------------------------------------------------------
# Backward-compatible API (used by existing code)
# --------------------------------------------------------------------------

def sign_data(data: Dict) -> bytes:
    """Sign the given data using Ed25519. Uses WA key if available, else ephemeral."""
    key = get_wa_private_key() or _get_ephemeral_key()
    message = json.dumps(data, sort_keys=True).encode()
    return key.sign(message)


def get_public_key_pem() -> str:
    """Return the Ed25519 public key in PEM format."""
    key = get_wa_private_key() or _get_ephemeral_key()
    pub = key.public_key()
    pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem.decode()
