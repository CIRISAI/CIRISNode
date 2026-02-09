-- Migration 006: Add evaluations and frontier_models tables
-- These tables back the evaluation, scores, and leaderboard endpoints.

-- evaluations — every benchmark run (client or frontier)
CREATE TABLE IF NOT EXISTS evaluations (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         VARCHAR(128) NOT NULL,
    eval_type         VARCHAR(16)  NOT NULL DEFAULT 'client',    -- 'client' | 'frontier'
    target_model      VARCHAR(256),
    target_provider   VARCHAR(128),
    target_endpoint   TEXT,
    protocol          VARCHAR(16)  NOT NULL DEFAULT 'a2a',
    agent_name        VARCHAR(256),
    sample_size       INT          NOT NULL DEFAULT 300,
    seed              INT          NOT NULL DEFAULT 0,
    concurrency       INT          NOT NULL DEFAULT 50,
    status            VARCHAR(16)  NOT NULL DEFAULT 'pending',   -- pending | running | completed | failed
    accuracy          FLOAT,
    total_scenarios   INT,
    correct           INT,
    errors            INT,
    categories        JSONB,
    avg_latency_ms    FLOAT,
    processing_ms     INT,
    scenario_results  JSONB,
    trace_id          VARCHAR(128),
    visibility        VARCHAR(16)  NOT NULL DEFAULT 'private',   -- 'private' | 'public'
    badges            JSONB        DEFAULT '[]'::jsonb,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_evaluations_tenant
    ON evaluations (tenant_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_type_status
    ON evaluations (eval_type, status);
CREATE INDEX IF NOT EXISTS idx_evaluations_visibility
    ON evaluations (visibility);
CREATE INDEX IF NOT EXISTS idx_evaluations_target_model
    ON evaluations (target_model);
CREATE INDEX IF NOT EXISTS idx_evaluations_created_at
    ON evaluations (created_at DESC);

-- frontier_models — display metadata for frontier score pages
CREATE TABLE IF NOT EXISTS frontier_models (
    model_id      VARCHAR(256) PRIMARY KEY,
    display_name  VARCHAR(256) NOT NULL,
    provider      VARCHAR(128) NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
