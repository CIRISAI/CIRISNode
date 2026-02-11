-- Migration 011: Add cost estimation + reasoning effort to frontier_models
-- Enables per-model cost tracking and reasoning effort control for o-series models.

ALTER TABLE frontier_models
  ADD COLUMN IF NOT EXISTS cost_per_1m_input NUMERIC(10,4),
  ADD COLUMN IF NOT EXISTS cost_per_1m_output NUMERIC(10,4),
  ADD COLUMN IF NOT EXISTS supports_reasoning BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS reasoning_effort VARCHAR(16);

-- Add constraint for valid reasoning_effort values
ALTER TABLE frontier_models DROP CONSTRAINT IF EXISTS valid_reasoning_effort;
ALTER TABLE frontier_models ADD CONSTRAINT valid_reasoning_effort
  CHECK (reasoning_effort IS NULL OR reasoning_effort IN ('low', 'medium', 'high'));
