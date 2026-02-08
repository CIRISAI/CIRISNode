-- Migration 003: Add agent_profiles table
-- Matches Engine alembic migration 003_add_agent_profiles.py

CREATE TABLE IF NOT EXISTS agent_profiles (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   VARCHAR(64) NOT NULL,
    name        VARCHAR(128) NOT NULL,
    spec        JSONB       NOT NULL,
    is_default  BOOLEAN     NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_profiles_tenant
    ON agent_profiles (tenant_id, name);
