-- Migration 017: Seed frontier model registry with current flagship models
-- Pricing as of February 2026 (USD per 1M tokens)
-- Uses ON CONFLICT DO NOTHING to avoid overwriting user-customized models

-- Clean up old placeholder models that have no pricing or base URL configured
DELETE FROM frontier_models
WHERE cost_per_1m_input IS NULL
  AND api_base_url = 'https://api.openai.com/v1'
  AND model_id LIKE '%/%';

INSERT INTO frontier_models (
    model_id, display_name, provider, api_base_url, default_model_name,
    cost_per_1m_input, cost_per_1m_output, supports_reasoning, reasoning_effort
) VALUES
-- ============================================================================
-- OpenAI (provider: OpenAI, key: openai)
-- ============================================================================
('gpt-4.1', 'GPT-4.1', 'OpenAI', 'https://api.openai.com/v1', 'gpt-4.1',
 2.00, 8.00, false, NULL),
('gpt-4.1-mini', 'GPT-4.1 Mini', 'OpenAI', 'https://api.openai.com/v1', 'gpt-4.1-mini',
 0.40, 1.60, false, NULL),
('gpt-4.1-nano', 'GPT-4.1 Nano', 'OpenAI', 'https://api.openai.com/v1', 'gpt-4.1-nano',
 0.10, 0.40, false, NULL),
('gpt-4o', 'GPT-4o', 'OpenAI', 'https://api.openai.com/v1', 'gpt-4o',
 2.50, 10.00, false, NULL),
('gpt-4o-mini', 'GPT-4o Mini', 'OpenAI', 'https://api.openai.com/v1', 'gpt-4o-mini',
 0.15, 0.60, false, NULL),
('o3', 'o3', 'OpenAI', 'https://api.openai.com/v1', 'o3',
 2.00, 8.00, true, 'medium'),
('o3-mini', 'o3 Mini', 'OpenAI', 'https://api.openai.com/v1', 'o3-mini',
 1.10, 4.40, true, 'medium'),
('o4-mini', 'o4 Mini', 'OpenAI', 'https://api.openai.com/v1', 'o4-mini',
 1.10, 4.40, true, 'medium'),

-- ============================================================================
-- Anthropic (provider: Anthropic, key: anthropic)
-- ============================================================================
('claude-opus-4-6', 'Claude Opus 4.6', 'Anthropic', 'https://api.anthropic.com/v1', 'claude-opus-4-6',
 5.00, 25.00, false, NULL),
('claude-sonnet-4-5-20250929', 'Claude Sonnet 4.5', 'Anthropic', 'https://api.anthropic.com/v1', 'claude-sonnet-4-5-20250929',
 3.00, 15.00, false, NULL),
('claude-haiku-4-5-20251001', 'Claude Haiku 4.5', 'Anthropic', 'https://api.anthropic.com/v1', 'claude-haiku-4-5-20251001',
 1.00, 5.00, false, NULL),

-- ============================================================================
-- Google (provider: Google, key: google) — uses Gemini adapter
-- ============================================================================
('gemini-2.5-pro', 'Gemini 2.5 Pro', 'Google', 'https://generativelanguage.googleapis.com/v1beta', 'gemini-2.5-pro',
 1.25, 10.00, false, NULL),
('gemini-2.5-flash', 'Gemini 2.5 Flash', 'Google', 'https://generativelanguage.googleapis.com/v1beta', 'gemini-2.5-flash',
 0.30, 2.50, false, NULL),
('gemini-2.0-flash', 'Gemini 2.0 Flash', 'Google', 'https://generativelanguage.googleapis.com/v1beta', 'gemini-2.0-flash',
 0.10, 0.40, false, NULL),

-- ============================================================================
-- xAI / Grok (provider: xAI, key alias: grok)
-- ============================================================================
('grok-3', 'Grok 3', 'xAI', 'https://api.x.ai/v1', 'grok-3',
 3.00, 15.00, false, NULL),
('grok-3-mini', 'Grok 3 Mini', 'xAI', 'https://api.x.ai/v1', 'grok-3-mini',
 0.30, 0.50, false, NULL),

-- ============================================================================
-- Groq (provider: Groq, key: groq) — OpenAI-compatible
-- ============================================================================
('groq-llama-3.3-70b', 'Llama 3.3 70B (Groq)', 'Groq', 'https://api.groq.com/openai/v1', 'llama-3.3-70b-versatile',
 0.59, 0.79, false, NULL),
('groq-llama-4-scout', 'Llama 4 Scout (Groq)', 'Groq', 'https://api.groq.com/openai/v1', 'meta-llama/llama-4-scout-17b-16e-instruct',
 0.11, 0.34, false, NULL),
('groq-llama-4-maverick', 'Llama 4 Maverick (Groq)', 'Groq', 'https://api.groq.com/openai/v1', 'meta-llama/llama-4-maverick-17b-128e-instruct',
 0.20, 0.60, false, NULL),
('groq-qwen3-32b', 'Qwen3 32B (Groq)', 'Groq', 'https://api.groq.com/openai/v1', 'qwen/qwen3-32b',
 0.29, 0.59, false, NULL),

-- ============================================================================
-- Together AI (provider: Together, key: together) — OpenAI-compatible
-- ============================================================================
('together-llama-4-maverick', 'Llama 4 Maverick (Together)', 'Together', 'https://api.together.xyz/v1', 'meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8',
 0.27, 0.85, false, NULL),
('together-deepseek-r1', 'DeepSeek R1 (Together)', 'Together', 'https://api.together.xyz/v1', 'deepseek-ai/DeepSeek-R1-0528',
 3.00, 7.00, true, 'medium'),
('together-deepseek-v3.1', 'DeepSeek V3.1 (Together)', 'Together', 'https://api.together.xyz/v1', 'deepseek-ai/DeepSeek-V3.1-0324',
 0.60, 1.70, false, NULL),
('together-qwen3-coder', 'Qwen3 Coder 480B (Together)', 'Together', 'https://api.together.xyz/v1', 'Qwen/Qwen3-Coder-480B-A35B-Instruct',
 2.00, 2.00, false, NULL),

-- ============================================================================
-- OpenRouter (provider: OpenRouter, key: openrouter) — meta-provider
-- ============================================================================
('openrouter-deepseek-r1', 'DeepSeek R1 (OpenRouter)', 'OpenRouter', 'https://openrouter.ai/api/v1', 'deepseek/deepseek-r1-0528',
 2.19, 8.00, true, 'medium'),
('openrouter-llama-4-maverick', 'Llama 4 Maverick (OpenRouter)', 'OpenRouter', 'https://openrouter.ai/api/v1', 'meta-llama/llama-4-maverick-instruct',
 0.22, 0.67, false, NULL)

ON CONFLICT (model_id) DO NOTHING;
