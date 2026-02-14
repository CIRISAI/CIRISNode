-- Migration 017: Ensure all tables exist in PostgreSQL
-- This completes the SQLite → PostgreSQL migration.
-- Uses CREATE TABLE IF NOT EXISTS so existing tables (from migrations 005/008/015/016) are untouched.

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

-- WBD task queue
CREATE TABLE IF NOT EXISTS wbd_tasks (
    id TEXT PRIMARY KEY,
    agent_task_id TEXT NOT NULL,
    payload TEXT,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    decision TEXT,
    comment TEXT,
    archived BOOLEAN DEFAULT FALSE,
    assigned_to TEXT,
    domain_hint TEXT,
    notified_at TIMESTAMPTZ
);

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
    deleted BOOLEAN DEFAULT FALSE,
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
    id INTEGER PRIMARY KEY CHECK (id = 1),
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

-- Indexes for frequently queried columns
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_wbd_tasks_status ON wbd_tasks(status);
CREATE INDEX IF NOT EXISTS idx_wbd_tasks_assigned ON wbd_tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_agent_events_agent_uid ON agent_events(agent_uid);
CREATE INDEX IF NOT EXISTS idx_agent_events_deleted ON agent_events(deleted) WHERE deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp DESC);
