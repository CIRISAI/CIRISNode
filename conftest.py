"""Root conftest — set env vars before any module imports."""

import os

os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("ENVIRONMENT", "test")
