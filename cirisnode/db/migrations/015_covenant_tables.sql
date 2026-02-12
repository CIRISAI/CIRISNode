-- Covenant trace ingestion and public key registration tables
-- These are used by the covenant endpoint for agent trace forwarding
-- with Ed25519 signature verification and CIRISRegistry cross-validation.

CREATE TABLE IF NOT EXISTS covenant_public_keys (
    key_id TEXT PRIMARY KEY,
    public_key_base64 TEXT NOT NULL,
    algorithm TEXT DEFAULT 'ed25519',
    description TEXT DEFAULT '',
    registered_by TEXT,
    org_id TEXT,
    registry_verified BOOLEAN DEFAULT FALSE,
    registry_status TEXT,
    registered_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS covenant_traces (
    id TEXT PRIMARY KEY,
    agent_uid TEXT,
    trace_id TEXT,
    thought_id TEXT,
    task_id TEXT,
    trace_level TEXT,
    trace_json JSONB,
    content_hash TEXT,
    signature_verified BOOLEAN DEFAULT FALSE,
    signing_key_id TEXT,
    received_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_covenant_traces_agent_uid ON covenant_traces(agent_uid);
CREATE INDEX IF NOT EXISTS idx_covenant_traces_received_at ON covenant_traces(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_covenant_traces_signing_key ON covenant_traces(signing_key_id);
