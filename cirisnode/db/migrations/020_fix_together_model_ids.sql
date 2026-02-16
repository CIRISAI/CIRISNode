-- Migration 020: Fix Together AI model IDs
-- V3.1 was "deepseek-ai/DeepSeek-V3.1-0324" (404), correct is "deepseek-ai/DeepSeek-V3.1"
-- R1 was "deepseek-ai/DeepSeek-R1-0528" (works but newer alias is "deepseek-ai/DeepSeek-R1")

UPDATE frontier_models
SET default_model_name = 'deepseek-ai/DeepSeek-V3.1'
WHERE model_id = 'together-deepseek-v3.1';

UPDATE frontier_models
SET default_model_name = 'deepseek-ai/DeepSeek-R1'
WHERE model_id = 'together-deepseek-r1';
