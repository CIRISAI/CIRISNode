-- Migration 009: Add missing created_at column to frontier_models
-- The table may have been created before migration 006 without this column.
ALTER TABLE frontier_models
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();
