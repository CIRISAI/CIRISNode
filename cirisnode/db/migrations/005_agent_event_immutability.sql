-- Migration 005: Agent event immutability (CIRISLens pattern)
-- Events are write-once. Admin mutations preserve original content hash.
-- Soft-delete replaces hard-delete.

ALTER TABLE agent_events ADD COLUMN IF NOT EXISTS original_content_hash TEXT;
ALTER TABLE agent_events ADD COLUMN IF NOT EXISTS deleted INTEGER DEFAULT 0;
ALTER TABLE agent_events ADD COLUMN IF NOT EXISTS deleted_by TEXT;
ALTER TABLE agent_events ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
ALTER TABLE agent_events ADD COLUMN IF NOT EXISTS archived_by TEXT;
ALTER TABLE agent_events ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP;
