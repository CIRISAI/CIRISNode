import logging
import os

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


def _load_cipher_key() -> bytes:
    """Load the Fernet encryption key from CIPHER_SECRET_KEY env var.

    - If set, use it directly (must be a valid Fernet key).
    - If not set in production, raise RuntimeError.
    - If not set in development/test, generate an ephemeral key and warn.
    """
    key = os.environ.get("CIPHER_SECRET_KEY")
    if key:
        return key.encode() if isinstance(key, str) else key

    # Detect production: ENVIRONMENT != "test" AND DATABASE_URL points to non-localhost
    environment = os.environ.get("ENVIRONMENT", "")
    db_url = os.environ.get("DATABASE_URL", "")
    is_prod = (
        environment != "test"
        and db_url
        and "localhost" not in db_url
        and "127.0.0.1" not in db_url
        and "db:" not in db_url
    )

    if is_prod:
        raise RuntimeError(
            "CIPHER_SECRET_KEY environment variable is required in production. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    generated_key = Fernet.generate_key()
    logger.warning(
        "CIPHER_SECRET_KEY not set — using ephemeral key. "
        "Encrypted data will be unrecoverable after restart. "
        "Set CIPHER_SECRET_KEY for persistent encryption."
    )
    return generated_key


SECRET_KEY = _load_cipher_key()
cipher = Fernet(SECRET_KEY)


def encrypt_data(data: str) -> str:
    """Encrypt the given data."""
    return cipher.encrypt(data.encode()).decode()


def decrypt_data(encrypted_data: str) -> str:
    """Decrypt the given data."""
    return cipher.decrypt(encrypted_data.encode()).decode()
