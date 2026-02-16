-- Migration 019: Fix OpenRouter Llama 4 Maverick model name
-- Was "meta-llama/llama-4-maverick-instruct" (404), correct is "meta-llama/llama-4-maverick"

UPDATE frontier_models
SET default_model_name = 'meta-llama/llama-4-maverick'
WHERE model_id = 'openrouter-llama-4-maverick';
