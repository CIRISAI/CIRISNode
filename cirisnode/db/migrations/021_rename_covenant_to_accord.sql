-- Rename covenant tables and indexes to accord.
-- This is a non-destructive rename; no data is lost.

ALTER TABLE IF EXISTS covenant_public_keys RENAME TO accord_public_keys;
ALTER TABLE IF EXISTS covenant_traces RENAME TO accord_traces;
ALTER TABLE IF EXISTS covenant_invocations RENAME TO accord_invocations;

ALTER INDEX IF EXISTS idx_covenant_traces_agent_uid RENAME TO idx_accord_traces_agent_uid;
ALTER INDEX IF EXISTS idx_covenant_traces_received_at RENAME TO idx_accord_traces_received_at;
ALTER INDEX IF EXISTS idx_covenant_traces_signing_key RENAME TO idx_accord_traces_signing_key;
ALTER INDEX IF EXISTS idx_covenant_invocations_target RENAME TO idx_accord_invocations_target;
ALTER INDEX IF EXISTS idx_covenant_invocations_created RENAME TO idx_accord_invocations_created;
