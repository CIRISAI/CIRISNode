-- Migration 007: Add frontier sweep columns to frontier_models
-- Adds api_base_url and default_model_name for sweep execution.

ALTER TABLE frontier_models
  ADD COLUMN IF NOT EXISTS api_base_url TEXT DEFAULT 'https://api.openai.com/v1',
  ADD COLUMN IF NOT EXISTS default_model_name VARCHAR(256);

UPDATE frontier_models SET default_model_name = model_id WHERE default_model_name IS NULL;
