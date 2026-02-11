-- Migration 010: Update valid_status constraint to include 'pending'
-- The frontier sweep inserts evaluations as 'pending' before running them,
-- but the check constraint only allowed running/completed/failed.

ALTER TABLE evaluations DROP CONSTRAINT IF EXISTS valid_status;
ALTER TABLE evaluations ADD CONSTRAINT valid_status
    CHECK (status IN ('pending', 'running', 'completed', 'failed'));
