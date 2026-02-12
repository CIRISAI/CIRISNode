-- Covenant Invocation System (CIS) audit log.
-- Records all shutdown directives issued by CIRISNode WA authority.

CREATE TABLE IF NOT EXISTS covenant_invocations (
    id TEXT PRIMARY KEY,
    target_agent_id TEXT NOT NULL,
    directive TEXT NOT NULL,
    reason TEXT,
    incident_id TEXT,
    authority_wa_id TEXT NOT NULL,
    issued_by TEXT,
    signature TEXT NOT NULL,
    delivered BOOLEAN DEFAULT FALSE,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_covenant_invocations_target ON covenant_invocations(target_agent_id);
CREATE INDEX IF NOT EXISTS idx_covenant_invocations_created ON covenant_invocations(created_at DESC);
