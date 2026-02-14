-- Migration 001: Ensure all core tables exist in PostgreSQL with full schemas.
-- Handles both fresh databases (CREATE TABLE) and existing databases
-- where tables may exist with partial schemas (ALTER TABLE ADD COLUMN).

-- Users (auth)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT,
    role TEXT NOT NULL DEFAULT 'anonymous',
    groups TEXT DEFAULT '',
    oauth_provider TEXT,
    oauth_sub TEXT
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS password TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS groups TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_sub TEXT;

-- WBD task queue
CREATE TABLE IF NOT EXISTS wbd_tasks (
    id TEXT PRIMARY KEY,
    agent_task_id TEXT,
    payload TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    decision TEXT,
    comment TEXT,
    archived BOOLEAN DEFAULT FALSE,
    assigned_to TEXT,
    domain_hint TEXT,
    notified_at TIMESTAMPTZ
);
ALTER TABLE wbd_tasks ADD COLUMN IF NOT EXISTS agent_task_id TEXT;
ALTER TABLE wbd_tasks ADD COLUMN IF NOT EXISTS payload TEXT;
ALTER TABLE wbd_tasks ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
ALTER TABLE wbd_tasks ADD COLUMN IF NOT EXISTS decision TEXT;
ALTER TABLE wbd_tasks ADD COLUMN IF NOT EXISTS comment TEXT;
ALTER TABLE wbd_tasks ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT FALSE;
ALTER TABLE wbd_tasks ADD COLUMN IF NOT EXISTS assigned_to TEXT;
ALTER TABLE wbd_tasks ADD COLUMN IF NOT EXISTS domain_hint TEXT;
ALTER TABLE wbd_tasks ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;

-- Agent events (observability)
CREATE TABLE IF NOT EXISTS agent_events (
    id TEXT PRIMARY KEY,
    node_ts TIMESTAMPTZ DEFAULT NOW(),
    agent_uid TEXT,
    event_json JSONB,
    original_content_hash TEXT,
    archived BOOLEAN DEFAULT FALSE,
    archived_by TEXT,
    archived_at TIMESTAMPTZ,
    deleted INTEGER DEFAULT 0,
    deleted_by TEXT,
    deleted_at TIMESTAMPTZ
);

-- Agent auth tokens
CREATE TABLE IF NOT EXISTS agent_tokens (
    token TEXT PRIMARY KEY,
    owner TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit trail
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_sha256 TEXT,
    details JSONB,
    archived BOOLEAN DEFAULT FALSE
);

-- Singleton config
CREATE TABLE IF NOT EXISTS config (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL,
    config_json JSONB NOT NULL
);

-- Legacy job tracking
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    results_url TEXT,
    results_json JSONB,
    archived BOOLEAN DEFAULT FALSE
);
