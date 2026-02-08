-- Migration 005: Agent event immutability (CIRISLens pattern)
-- Events are write-once. Admin mutations preserve original content hash.
-- Soft-delete replaces hard-delete.

ALTER TABLE agent_events ADD COLUMN original_content_hash TEXT;
ALTER TABLE agent_events ADD COLUMN deleted INTEGER DEFAULT 0;
ALTER TABLE agent_events ADD COLUMN deleted_by TEXT;
ALTER TABLE agent_events ADD COLUMN deleted_at TIMESTAMP;
ALTER TABLE agent_events ADD COLUMN archived_by TEXT;
ALTER TABLE agent_events ADD COLUMN archived_at TIMESTAMP;
