-- Migration 018: Trim frontier models to top flagships only
-- Removes lower-tier and duplicate models seeded by 017's initial run

DELETE FROM frontier_models WHERE model_id IN (
    'gpt-4.1-mini',
    'gpt-4.1-nano',
    'gpt-4o-mini',
    'o3-mini',
    'claude-haiku-4-5-20251001',
    'gemini-2.0-flash',
    'grok-3-mini',
    'groq-llama-3.3-70b',
    'groq-llama-4-scout',
    'groq-qwen3-32b',
    'together-llama-4-maverick',
    'together-qwen3-coder',
    'openrouter-deepseek-r1'
);
