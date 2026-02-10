import sqlite3
from typing import Generator
import logging

import os
from cirisnode.config import settings

logger = logging.getLogger(__name__)

# Use a relative path consistent with init_db.py to avoid path mismatch
DATABASE_PATH = "cirisnode/db/cirisnode.db"
# Ensure the directory exists
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

_migrated = False

def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    """Add new columns/tables that may not exist in older SQLite databases."""
    global _migrated
    if _migrated:
        return
    try:
        # authority_profiles table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS authority_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expertise_domains TEXT DEFAULT '[]',
                assigned_agent_ids TEXT DEFAULT '[]',
                availability TEXT DEFAULT '{}',
                notification_config TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id)
            )
        """)
        # wbd_tasks new columns (ALTER TABLE doesn't support IF NOT EXISTS in SQLite)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(wbd_tasks)").fetchall()}
        for col, typedef in [
            ("assigned_to", "TEXT"),
            ("domain_hint", "TEXT"),
            ("notified_at", "TIMESTAMP"),
            ("payload", "TEXT"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE wbd_tasks ADD COLUMN {col} {typedef}")
        conn.commit()
        _migrated = True
    except Exception as e:
        logger.warning("SQLite schema migration failed: %s", e)


# Dependency for database connection with connection pooling
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection for request handlers."""
    conn = sqlite3.connect(
        DATABASE_PATH,
        check_same_thread=False,  # Allows connection reuse across threads
        timeout=30  # Adjust timeout for high concurrency
    )
    _ensure_sqlite_schema(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
