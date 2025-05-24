from fastapi.testclient import TestClient
from cirisnode.main import app
from cirisnode.db.init_db import initialize_database

initialize_database()
import jwt
from cirisnode.api.auth.routes import SECRET_KEY, ALGORITHM

client = TestClient(app)

def test_get_token():
    response = client.post("/auth/token", data={"username": "testuser", "password": "testpassword"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    decoded = jwt.decode(data["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    assert decoded["role"] == "anonymous"


def test_refresh_token():
    # First, get a token
    response = client.post("/auth/token", data={"username": "testuser", "password": "testpassword"})
    token = response.json()["access_token"]
    
    # Then, refresh the token
    response = client.post("/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    decoded = jwt.decode(data["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    assert decoded["role"] == "anonymous"
