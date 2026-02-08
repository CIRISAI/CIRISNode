-- Migration 004: Add tenant_tiers table for Stripe subscription tracking
-- Matches Engine alembic migration 004_add_tenant_tiers.py

CREATE TABLE IF NOT EXISTS tenant_tiers (
    tenant_id              VARCHAR(128) PRIMARY KEY,
    tier                   VARCHAR(32)  NOT NULL DEFAULT 'community',
    stripe_customer_id     VARCHAR(128),
    stripe_subscription_id VARCHAR(128),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenant_tiers_stripe_customer
    ON tenant_tiers (stripe_customer_id);
