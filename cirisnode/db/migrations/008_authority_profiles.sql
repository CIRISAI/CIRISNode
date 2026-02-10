-- Authority profile for wise authorities (and admins who resolve WBD)
CREATE TABLE IF NOT EXISTS authority_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expertise_domains JSONB DEFAULT '[]',
    assigned_agent_ids JSONB DEFAULT '[]',
    availability JSONB DEFAULT '{}',
    notification_config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id)
);

-- WBD task routing fields
ALTER TABLE wbd_tasks
    ADD COLUMN IF NOT EXISTS assigned_to TEXT,
    ADD COLUMN IF NOT EXISTS domain_hint TEXT,
    ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
