# 001: Agent Events - Missing Tables and SQLite Syntax

**Status**: Open
**Priority**: High
**Reported**: 2026-02-08
**Reporter**: Infrastructure (via CIRISAgent adapter testing)

## Summary

The `/api/v1/agent/events` endpoints return 401 "Invalid agent token" for valid tokens because the required database tables don't exist and the SQL uses SQLite syntax instead of PostgreSQL.

## Symptoms

- POST to `/api/v1/agent/events` with `X-Agent-Token` header returns:
  ```json
  {"detail": "Invalid agent token"}
  ```
- This happens regardless of token value because the underlying query fails

## Root Cause

### 1. Missing Tables

The `agent_tokens` and `agent_events` tables don't exist in the PostgreSQL database:

```sql
-- Current tables in cirisnode DB:
-- agent_profiles, evaluations, frontier_models, schema_migrations, tenant_tiers

-- Missing:
-- agent_tokens
-- agent_events
```

### 2. SQLite Syntax in PostgreSQL Context

`cirisnode/api/agent/routes.py` uses SQLite-style `?` placeholders:

```python
# Line 27-30
token_row = conn.execute(
    "SELECT token FROM agent_tokens WHERE token = ?",
    (x_agent_token,)
).fetchone()

# Line 36-41
conn.execute(
    """
    INSERT INTO agent_events (id, node_ts, agent_uid, event_json)
    VALUES (?, ?, ?, ?)
    """,
    (event_id, datetime.datetime.utcnow(), request.agent_uid, json.dumps(request.event))
)
```

PostgreSQL requires `$1, $2, ...` placeholders.

## Fix Required

### 1. Add Migration

Create `cirisnode/db/migrations/005_add_agent_events.sql`:

```sql
CREATE TABLE IF NOT EXISTS agent_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token TEXT UNIQUE NOT NULL,
    agent_uid TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS agent_events (
    id UUID PRIMARY KEY,
    node_ts TIMESTAMPTZ NOT NULL,
    agent_uid TEXT NOT NULL,
    event_json JSONB,
    archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agent_events_agent_uid ON agent_events(agent_uid);
CREATE INDEX idx_agent_events_node_ts ON agent_events(node_ts DESC);
```

### 2. Update SQL Syntax

In `cirisnode/api/agent/routes.py`, change all `?` to positional params:

```python
# Before
"SELECT token FROM agent_tokens WHERE token = ?"

# After
"SELECT token FROM agent_tokens WHERE token = $1"
```

### 3. Use Async PostgreSQL

The routes use sync `conn.execute()` but should use the async pool pattern like other routes.

## Affected Components

- `cirisnode/api/agent/routes.py` - All 4 endpoints
- CIRISAgent `cirisnode` adapter - Cannot post agent events

## Testing

After fix:
```bash
# Create a test token
docker exec ciris-postgres psql -U ciris -d cirisnode -c \
  "INSERT INTO agent_tokens (token, agent_uid, description) VALUES ('test-token-123', 'test-agent', 'Test token');"

# Test POST
curl -X POST https://ethicsengine.ciris.ai/api/v1/agent/events \
  -H "Content-Type: application/json" \
  -H "X-Agent-Token: test-token-123" \
  -d '{"agent_uid": "test-agent", "event": {"type": "test"}}'

# Should return {"id": "...", "status": "ok"}
```
