-- Soft-delete support: archived evaluations are hidden from all public queries
-- but retained for 5 days before permanent purge.
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_evaluations_archived_at ON evaluations (archived_at) WHERE archived_at IS NOT NULL;
