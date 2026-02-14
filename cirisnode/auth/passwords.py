"""Password hashing using stdlib (SHA-256 + salt).

No external dependencies required. Legacy plaintext passwords are
accepted for backward compatibility and should be migrated on login.
"""

import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    """Hash a password with a random salt using SHA-256.

    Returns a string in the format: salt$hash
    """
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}${password}".encode()).hexdigest()
    return f"{salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored hash.

    Handles both:
    - New format: salt$hash (SHA-256)
    - Legacy format: plaintext (for migration — caller should rehash)

    Returns True if the password matches.
    """
    if not stored:
        return False

    if "$" not in stored:
        # Legacy plaintext — constant-time comparison
        return hmac.compare_digest(password, stored)

    salt, expected_hash = stored.split("$", 1)
    actual_hash = hashlib.sha256(f"{salt}${password}".encode()).hexdigest()
    return hmac.compare_digest(actual_hash, expected_hash)
