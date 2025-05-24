import sqlite3
from fastapi.testclient import TestClient
from cirisnode.main import app
from cirisnode.db.init_db import initialize_database

initialize_database()

client = TestClient(app)

DB_PATH = "cirisnode/db/cirisnode.db"


def _get_token(username: str):
    resp = client.post("/auth/token", data={"username": username, "password": "pwd"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_config_access_rbac():
    anon_token = _get_token("anon")
    r = client.get("/api/v1/config", headers={"Authorization": f"Bearer {anon_token}"})
    assert r.status_code == 403

    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET role = 'admin' WHERE username = ?", ("admin",))
    conn.commit()
    conn.close()
    admin_token = _get_token("admin")
    r = client.get("/api/v1/config", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["version"] == 1
