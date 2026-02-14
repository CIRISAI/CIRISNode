from fastapi.testclient import TestClient
from cirisnode.main import app
from cirisnode.config import settings
from cirisnode.database import DATABASE_PATH
import jwt
import sqlite3

client = TestClient(app)

def get_auth_header(role="admin"):
    token = jwt.encode({"sub": "testuser", "role": role}, settings.JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}

def test_submit_wbd_task_unsigned():
    """Unsigned WBD submissions should be rejected with 403."""
    headers = get_auth_header()
    response = client.post(
        "/api/v1/wbd/submit",
        json={"agent_task_id": "task_123", "payload": "Test payload"},
        headers=headers
    )
    assert response.status_code == 403
    data = response.json()
    assert "signed" in data["detail"].lower() or "signature" in data["detail"].lower()

def test_get_wbd_tasks():
    """Admin should be able to list WBD tasks."""
    headers = get_auth_header("admin")
    response = client.get("/api/v1/wbd/tasks", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)

def test_get_wbd_tasks_unauthenticated():
    """Unauthenticated request to list tasks should fail."""
    response = client.get("/api/v1/wbd/tasks")
    assert response.status_code in (401, 422)

def test_resolve_wbd_task_unauthenticated():
    """Unauthenticated resolve should return 401/422."""
    response = client.post(
        "/api/v1/wbd/tasks/nonexistent/resolve",
        json={"decision": "approve", "comment": "test"},
    )
    assert response.status_code in (401, 422)

def test_resolve_wbd_task_requires_authority():
    """Regular user role should not be able to resolve WBD tasks."""
    headers = get_auth_header("user")
    response = client.post(
        "/api/v1/wbd/tasks/nonexistent/resolve",
        json={"decision": "approve", "comment": "test"},
        headers=headers
    )
    assert response.status_code == 403

def test_get_single_wbd_task_not_found():
    """Getting a non-existent task should return 404."""
    response = client.get("/api/v1/wbd/tasks/nonexistent")
    assert response.status_code == 404

def test_resolve_wbd_task_not_found():
    """Resolving a non-existent task should return 404 (with proper auth)."""
    headers = get_auth_header("admin")
    response = client.post(
        "/api/v1/wbd/tasks/nonexistent/resolve",
        json={"decision": "approve", "comment": "test"},
        headers=headers
    )
    assert response.status_code == 404
