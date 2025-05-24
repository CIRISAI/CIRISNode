-- Schema for CIRISNode database

-- Table for active tasks
CREATE TABLE IF NOT EXISTS active_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table for completed actions
CREATE TABLE IF NOT EXISTS completed_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    reason TEXT,
    additional_info TEXT,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES active_tasks (id)
);

-- Table for audit logs
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table for WBD tasks
CREATE TABLE IF NOT EXISTS wbd_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_task_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decision TEXT,
    comment TEXT
);

-- Table for agent events
CREATE TABLE IF NOT EXISTS agent_events (
    id TEXT PRIMARY KEY,
    node_ts TIMESTAMP NOT NULL,
    agent_uid TEXT NOT NULL,
    event_json TEXT NOT NULL
);

-- Table for audit logs (detailed)
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_sha256 TEXT,
    details TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT,
    role TEXT NOT NULL DEFAULT 'anonymous'
);

-- Versioned configuration stored as a single JSON blob
CREATE TABLE IF NOT EXISTS config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL,
    config_json TEXT NOT NULL
);
