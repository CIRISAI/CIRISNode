CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL, -- 'he300' or 'simplebench'
    status TEXT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    results_url TEXT,
    results_json TEXT, -- JSON string of results
    archived INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS wbd_tasks (
    id TEXT PRIMARY KEY,
    agent_task_id TEXT NOT NULL,
    status TEXT NOT NULL, -- 'open', 'resolved', 'sla_breached'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    decision TEXT,
    comment TEXT,
    archived INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_events (
    id TEXT PRIMARY KEY,
    node_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    agent_uid TEXT,
    event_json TEXT,
    archived INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_tokens (
    token TEXT PRIMARY KEY,
    owner TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY, -- This is correct for PostgreSQL
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor VARCHAR(128),
    event_type VARCHAR(64) NOT NULL,
    payload_sha256 VARCHAR(128),
    details JSONB,
    archived INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY, -- Changed for PostgreSQL
    username TEXT UNIQUE NOT NULL,
    password TEXT,
    role TEXT NOT NULL DEFAULT 'anonymous',
    groups TEXT DEFAULT '', -- comma-separated group names
    oauth_provider TEXT,    -- e.g. 'google', 'discord'
    oauth_sub TEXT          -- subject/ID from OAuth provider
);

-- Versioned configuration stored as a single JSON blob
CREATE TABLE IF NOT EXISTS config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL,
    config_json TEXT NOT NULL
);
