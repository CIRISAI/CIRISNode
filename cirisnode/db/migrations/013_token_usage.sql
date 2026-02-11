-- Add token_usage JSONB column to evaluations table.
-- Stores per-evaluation aggregated token counts and computed cost:
--   {"input_tokens": N, "output_tokens": N, "reasoning_tokens": N, "cost_usd": X.XX}
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS token_usage JSONB;
