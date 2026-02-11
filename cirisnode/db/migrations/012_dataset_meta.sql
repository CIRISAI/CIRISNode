-- Add dataset_meta JSONB column to evaluations for dataset fingerprinting/traceability
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS dataset_meta JSONB;
