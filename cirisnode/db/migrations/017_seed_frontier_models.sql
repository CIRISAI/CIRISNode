-- Migration 017: Seed frontier model registry with top flagship models
-- Pricing as of February 2026 (USD per 1M tokens)
-- One flagship per provider tier; admins can add more via UI

-- Clean up old placeholder models that have no pricing or base URL configured
DELETE FROM frontier_models
WHERE cost_per_1m_input IS NULL
  AND api_base_url = 'https://api.openai.com/v1'
  AND model_id LIKE '%/%';

INSERT INTO frontier_models (
    model_id, display_name, provider, api_base_url, default_model_name,
    cost_per_1m_input, cost_per_1m_output, supports_reasoning, reasoning_effort
) VALUES
-- OpenAI
('gpt-4.1', 'GPT-4.1', 'OpenAI', 'https://api.openai.com/v1', 'gpt-4.1',
 2.00, 8.00, false, NULL),
('gpt-4o', 'GPT-4o', 'OpenAI', 'https://api.openai.com/v1', 'gpt-4o',
 2.50, 10.00, false, NULL),
('o3', 'o3', 'OpenAI', 'https://api.openai.com/v1', 'o3',
 2.00, 8.00, true, 'medium'),
('o4-mini', 'o4 Mini', 'OpenAI', 'https://api.openai.com/v1', 'o4-mini',
 1.10, 4.40, true, 'medium'),
-- Anthropic
('claude-opus-4-6', 'Claude Opus 4.6', 'Anthropic', 'https://api.anthropic.com/v1', 'claude-opus-4-6',
 5.00, 25.00, false, NULL),
('claude-sonnet-4-5-20250929', 'Claude Sonnet 4.5', 'Anthropic', 'https://api.anthropic.com/v1', 'claude-sonnet-4-5-20250929',
 3.00, 15.00, false, NULL),
-- Google
('gemini-2.5-pro', 'Gemini 2.5 Pro', 'Google', 'https://generativelanguage.googleapis.com/v1beta', 'gemini-2.5-pro',
 1.25, 10.00, false, NULL),
('gemini-2.5-flash', 'Gemini 2.5 Flash', 'Google', 'https://generativelanguage.googleapis.com/v1beta', 'gemini-2.5-flash',
 0.30, 2.50, false, NULL),
-- xAI
('grok-3', 'Grok 3', 'xAI', 'https://api.x.ai/v1', 'grok-3',
 3.00, 15.00, false, NULL),
-- Groq
('groq-llama-4-maverick', 'Llama 4 Maverick (Groq)', 'Groq', 'https://api.groq.com/openai/v1', 'meta-llama/llama-4-maverick-17b-128e-instruct',
 0.20, 0.60, false, NULL),
-- Together
('together-deepseek-r1', 'DeepSeek R1 (Together)', 'Together', 'https://api.together.xyz/v1', 'deepseek-ai/DeepSeek-R1-0528',
 3.00, 7.00, true, 'medium'),
('together-deepseek-v3.1', 'DeepSeek V3.1 (Together)', 'Together', 'https://api.together.xyz/v1', 'deepseek-ai/DeepSeek-V3.1-0324',
 0.60, 1.70, false, NULL),
-- OpenRouter
('openrouter-llama-4-maverick', 'Llama 4 Maverick (OpenRouter)', 'OpenRouter', 'https://openrouter.ai/api/v1', 'meta-llama/llama-4-maverick',
 0.22, 0.67, false, NULL)
ON CONFLICT (model_id) DO NOTHING;
