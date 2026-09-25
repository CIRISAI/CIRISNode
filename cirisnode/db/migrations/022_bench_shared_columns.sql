-- Migration 022: columns CIRISBench's SQLAlchemy model expects on the shared tables
--
-- CIRISBench (engine/db/models.py) reads/writes evaluations and frontier_models through
-- its own model, which declares columns that only ever existed on the EU database (where
-- bench's Alembic chain 002_add_checkpoint_columns was run by hand in Feb 2026). On the US
-- database — now the single primary for both regions (CIRISCore#2) — every bench write and
-- bench's startup crash-recovery pass fail with UndefinedColumnError. See CIRISNode#37,
-- CIRISNode#34, CIRISBench#8.
--
-- Purely additive; every statement is idempotent. Types and defaults match the EU
-- definitions exactly so the two historical shapes converge.

ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS model_version            VARCHAR(64);
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS batch_config             JSONB;
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS completed_scenario_count INTEGER     NOT NULL DEFAULT 0;
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS checkpoint_at            TIMESTAMPTZ;
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS trace_binding            JSONB;

-- Bench's crash-recovery query filters on status = 'running' (engine/api/main.py).
CREATE INDEX IF NOT EXISTS idx_evaluations_running_checkpoint
    ON evaluations (checkpoint_at) WHERE status = 'running';

-- frontier_models keeps model_id as its primary key (006). Bench's model declares a uuid
-- `id`; add it as a unique, defaulted column so ORM inserts work without changing the PK.
ALTER TABLE frontier_models ADD COLUMN IF NOT EXISTS id             UUID        NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE frontier_models ADD COLUMN IF NOT EXISTS provider_label VARCHAR(64);
ALTER TABLE frontier_models ADD COLUMN IF NOT EXISTS active         BOOLEAN     NOT NULL DEFAULT true;
ALTER TABLE frontier_models ADD COLUMN IF NOT EXISTS proxy_route    VARCHAR(256);
ALTER TABLE frontier_models ADD COLUMN IF NOT EXISTS eval_config    JSONB;
ALTER TABLE frontier_models ADD COLUMN IF NOT EXISTS added_at       TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE UNIQUE INDEX IF NOT EXISTS idx_frontier_models_id ON frontier_models (id);
