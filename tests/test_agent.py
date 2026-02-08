from fastapi.testclient import TestClient
from cirisnode.main import app
from cirisnode.database import DATABASE_PATH
import jwt
import sqlite3

client = TestClient(app)

# Helper for generating a static JWT for test purposes
TEST_SECRET = "testsecret"
TEST_AGENT_TOKEN = "test-agent-token-abc123"


def _ensure_agent_token():
    """Insert a test agent token into the DB if not present."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO agent_tokens (token, owner) VALUES (?, ?)",
        (TEST_AGENT_TOKEN, "test-agent"),
    )
    conn.commit()
    conn.close()


def get_admin_header():
    token = jwt.encode({"sub": "testuser", "role": "admin"}, TEST_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def get_agent_header():
    _ensure_agent_token()
    return {"X-Agent-Token": TEST_AGENT_TOKEN}


def test_push_agent_event():
    headers = get_agent_header()
    response = client.post(
        "/api/v1/agent/events",
        json={"agent_uid": "agent_789", "event": {"type": "Task", "data": "Sample task data"}},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "id" in data
    assert "content_hash" in data


def test_push_agent_event_no_token():
    """POST without agent token should be rejected."""
    response = client.post(
        "/api/v1/agent/events",
        json={"agent_uid": "agent_789", "event": {"type": "Task", "data": "test"}},
    )
    assert response.status_code in (401, 422)


def test_push_agent_event_invalid_token():
    """POST with invalid agent token should be 401."""
    response = client.post(
        "/api/v1/agent/events",
        json={"agent_uid": "agent_789", "event": {"type": "Task", "data": "test"}},
        headers={"X-Agent-Token": "invalid-token"},
    )
    assert response.status_code == 401


def test_get_agent_events():
    headers = get_agent_header()
    # Create one first
    client.post(
        "/api/v1/agent/events",
        json={"agent_uid": "agent_789", "event": {"type": "Task", "data": "for listing"}},
        headers=headers,
    )
    response = client.get("/api/v1/agent/events", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "content_hash" in data[0]


def test_get_agent_events_no_token():
    """GET without token should be rejected."""
    response = client.get("/api/v1/agent/events")
    assert response.status_code in (401, 422)


def test_delete_agent_event_requires_admin():
    """DELETE without admin JWT should be rejected."""
    agent_headers = get_agent_header()
    # Create an event
    resp = client.post(
        "/api/v1/agent/events",
        json={"agent_uid": "agent_789", "event": {"type": "Task", "data": "to delete"}},
        headers=agent_headers,
    )
    event_id = resp.json()["id"]
    # Try delete without auth — should fail
    response = client.delete(f"/api/v1/agent/events/{event_id}")
    assert response.status_code in (401, 422)


def test_delete_agent_event_admin():
    """DELETE with admin JWT should soft-delete and return content hash."""
    agent_headers = get_agent_header()
    resp = client.post(
        "/api/v1/agent/events",
        json={"agent_uid": "agent_789", "event": {"type": "Task", "data": "admin delete test"}},
        headers=agent_headers,
    )
    event_id = resp.json()["id"]
    admin_headers = get_admin_header()
    response = client.delete(f"/api/v1/agent/events/{event_id}", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "soft_deleted"
    assert "original_content_hash" in data


def test_archive_agent_event_requires_admin():
    """PATCH archive without admin JWT should be rejected."""
    agent_headers = get_agent_header()
    resp = client.post(
        "/api/v1/agent/events",
        json={"agent_uid": "agent_789", "event": {"type": "Task", "data": "to archive"}},
        headers=agent_headers,
    )
    event_id = resp.json()["id"]
    response = client.patch(
        f"/api/v1/agent/events/{event_id}/archive?archived=true",
    )
    assert response.status_code in (401, 422)


def test_archive_agent_event_admin():
    """PATCH archive with admin JWT should succeed and return content hash."""
    agent_headers = get_agent_header()
    resp = client.post(
        "/api/v1/agent/events",
        json={"agent_uid": "agent_789", "event": {"type": "Task", "data": "admin archive test"}},
        headers=agent_headers,
    )
    event_id = resp.json()["id"]
    admin_headers = get_admin_header()
    response = client.patch(
        f"/api/v1/agent/events/{event_id}/archive?archived=true",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["archived"] is True
    assert "original_content_hash" in data


def test_soft_deleted_events_hidden():
    """Soft-deleted events should not appear in GET listing."""
    agent_headers = get_agent_header()
    admin_headers = get_admin_header()
    # Create and soft-delete
    resp = client.post(
        "/api/v1/agent/events",
        json={"agent_uid": "agent_789", "event": {"type": "Task", "data": "hidden test"}},
        headers=agent_headers,
    )
    event_id = resp.json()["id"]
    client.delete(f"/api/v1/agent/events/{event_id}", headers=admin_headers)
    # List events — soft-deleted should not appear
    response = client.get("/api/v1/agent/events", headers=agent_headers)
    ids = [e["id"] for e in response.json()]
    assert event_id not in ids
