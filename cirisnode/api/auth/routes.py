from fastapi import APIRouter, HTTPException, status, Depends, Form, Header, Request
from cirisnode.database import get_db
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import jwt
from cirisnode.utils.rbac import require_role
import hashlib
import json

SECRET_KEY = "testsecret"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

auth_router = APIRouter()

class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None
    role: str = "anonymous"


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    groups: str = ''
    oauth_provider: Optional[str] = None
    oauth_sub: Optional[str] = None

class RoleUpdateRequest(BaseModel):
    role: str

class GroupUpdateRequest(BaseModel):
    groups: str  # comma-separated

class OAuthUpdateRequest(BaseModel):
    oauth_provider: str
    oauth_sub: str


@auth_router.post("/auth/token", response_model=Token)
def login_for_access_token(
    username: str = Form(...),
    password: str = Form(...),
    db=Depends(get_db),
):
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    row = conn.execute(
        "SELECT password, role FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None:
        # Auto-create user with anonymous role
        conn.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, 'anonymous')",
            (username, password),
        )
        conn.commit()
        role = "anonymous"
    else:
        stored_pw, role = row
        if stored_pw != password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

    to_encode = {
        "sub": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": encoded_jwt, "token_type": "bearer"}

@auth_router.post("/auth/refresh", response_model=Token)
def refresh_access_token(Authorization: str = Header(...)):
    # Extract token from header
    if not Authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = Authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        role = payload.get("role", "anonymous")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    # Issue new token
    to_encode = {
        "sub": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": encoded_jwt, "token_type": "bearer"}

@auth_router.get("/auth/users", dependencies=[Depends(require_role(["admin"]))], response_model=list[UserOut])
def list_users(db=Depends(get_db)):
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    users = conn.execute("SELECT id, username, role, groups, oauth_provider, oauth_sub FROM users").fetchall()
    return [UserOut(id=row[0], username=row[1], role=row[2], groups=row[3] or '', oauth_provider=row[4], oauth_sub=row[5]) for row in users]

@auth_router.post("/auth/users/{username}/role", dependencies=[Depends(require_role(["admin"]))])
def update_user_role(username: str, req: RoleUpdateRequest, Authorization: str = Header(...), db=Depends(get_db)):
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    user = conn.execute("SELECT id, username, role FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    old_role = user[2]
    conn.execute("UPDATE users SET role = ? WHERE username = ?", (req.role, username))
    conn.commit()
    # Audit log
    actor = get_actor_from_token(Authorization)
    payload = json.dumps({"username": username, "old_role": old_role, "new_role": req.role})
    payload_sha256 = hashlib.sha256(payload.encode()).hexdigest()
    conn.execute(
        "INSERT INTO audit_logs (actor, event_type, payload_sha256, details) VALUES (?, ?, ?, ?)",
        (actor, "role_update", payload_sha256, payload)
    )
    conn.commit()
    return {"status": "updated", "username": username, "old_role": old_role, "new_role": req.role}

@auth_router.post("/auth/users/{username}/groups", dependencies=[Depends(require_role(["admin"]))])
def update_user_groups(username: str, req: GroupUpdateRequest, Authorization: str = Header(...), db=Depends(get_db)):
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    user = conn.execute("SELECT id, username, groups FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    old_groups = user[2] or ''
    conn.execute("UPDATE users SET groups = ? WHERE username = ?", (req.groups, username))
    conn.commit()
    # Audit log
    actor = get_actor_from_token(Authorization)
    payload = json.dumps({"username": username, "old_groups": old_groups, "new_groups": req.groups})
    payload_sha256 = hashlib.sha256(payload.encode()).hexdigest()
    conn.execute(
        "INSERT INTO audit_logs (actor, event_type, payload_sha256, details) VALUES (?, ?, ?, ?)",
        (actor, "group_update", payload_sha256, payload)
    )
    conn.commit()
    return {"status": "updated", "username": username, "old_groups": old_groups, "new_groups": req.groups}

@auth_router.post("/auth/users/{username}/oauth", dependencies=[Depends(require_role(["admin"]))])
def update_user_oauth(username: str, req: OAuthUpdateRequest, Authorization: str = Header(...), db=Depends(get_db)):
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    user = conn.execute("SELECT id, username, oauth_provider, oauth_sub FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    old_provider, old_sub = user[2], user[3]
    conn.execute("UPDATE users SET oauth_provider = ?, oauth_sub = ? WHERE username = ?", (req.oauth_provider, req.oauth_sub, username))
    conn.commit()
    # Audit log
    actor = get_actor_from_token(Authorization)
    payload = json.dumps({"username": username, "old_oauth_provider": old_provider, "old_oauth_sub": old_sub, "new_oauth_provider": req.oauth_provider, "new_oauth_sub": req.oauth_sub})
    payload_sha256 = hashlib.sha256(payload.encode()).hexdigest()
    conn.execute(
        "INSERT INTO audit_logs (actor, event_type, payload_sha256, details) VALUES (?, ?, ?, ?)",
        (actor, "oauth_update", payload_sha256, payload)
    )
    conn.commit()
    return {"status": "updated", "username": username, "oauth_provider": req.oauth_provider, "oauth_sub": req.oauth_sub}

@auth_router.delete("/auth/users/{username}", dependencies=[Depends(require_role(["admin"]))])
def delete_user(username: str, Authorization: str = Header(...), db=Depends(get_db)):
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    user = conn.execute("SELECT id, username FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    conn.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    # Audit log
    actor = get_actor_from_token(Authorization)
    payload = json.dumps({"username": username})
    payload_sha256 = hashlib.sha256(payload.encode()).hexdigest()
    conn.execute(
        "INSERT INTO audit_logs (actor, event_type, payload_sha256, details) VALUES (?, ?, ?, ?)",
        (actor, "user_delete", payload_sha256, payload)
    )
    conn.commit()
    return {"status": "deleted", "username": username}

@auth_router.get("/auth/me", response_model=UserOut)
def get_me(request: Request, db=Depends(get_db)):
    # Prefer JWT token for identity (not spoofable)
    auth_header = request.headers.get("authorization", "")
    email = None
    if auth_header.startswith("Bearer "):
        actor = get_actor_from_token(auth_header)
        if actor != "unknown":
            email = actor
    # Fallback: X-User-Email (trusted only behind reverse proxy)
    if not email:
        email = request.headers.get("x-user-email")
    if not email:
        raise HTTPException(status_code=401, detail="Authentication required")
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    user = conn.execute("SELECT id, username, role, groups, oauth_provider, oauth_sub FROM users WHERE username = ?", (email,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(id=user[0], username=user[1], role=user[2], groups=user[3] or '', oauth_provider=user[4], oauth_sub=user[5])

def get_actor_from_token(Authorization: str) -> str:
    if not Authorization.startswith("Bearer "):
        return "unknown"
    token = Authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub", "unknown")
    except Exception:
        return "unknown"
