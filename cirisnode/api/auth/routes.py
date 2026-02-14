import hashlib
import json
import logging

from fastapi import APIRouter, HTTPException, status, Depends, Form, Header, Request, Query
from cirisnode.db.pg_pool import get_pg_pool
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Optional, List
import jwt
from cirisnode.auth.dependencies import require_role, decode_jwt, get_actor_from_token, ALGORITHM
from cirisnode.auth.passwords import hash_password, verify_password
from cirisnode.config import settings

logger = logging.getLogger(__name__)

ACCESS_TOKEN_EXPIRE_MINUTES = 60
ALLOWED_ADMIN_DOMAIN = "ciris.ai"

auth_router = APIRouter()

class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None
    role: str = "anonymous"


class UserOut(BaseModel):
    id: Optional[int] = None
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

class InviteRequest(BaseModel):
    email: str
    role: str = "wise_authority"
    expertise_domains: Optional[List[str]] = None
    assigned_agent_ids: Optional[List[str]] = None


@auth_router.post("/auth/token", response_model=Token)
async def login_for_access_token(
    username: str = Form(...),
    password: str = Form(...),
):
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT password, role FROM users WHERE username = $1",
            username,
        )
        if row is None:
            # Auto-create user with anonymous role (hashed password)
            await conn.execute(
                "INSERT INTO users (username, password, role) VALUES ($1, $2, 'anonymous')",
                username, hash_password(password),
            )
            role = "anonymous"
        else:
            stored_pw, role = row["password"], row["role"]
            if not verify_password(password, stored_pw):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Incorrect username or password",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # Auto-migrate legacy plaintext passwords to hashed
            if stored_pw and "$" not in stored_pw:
                await conn.execute(
                    "UPDATE users SET password = $1 WHERE username = $2",
                    hash_password(password), username,
                )

    to_encode = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=ALGORITHM)
    return {"access_token": encoded_jwt, "token_type": "bearer"}

@auth_router.post("/auth/refresh", response_model=Token)
def refresh_access_token(Authorization: str = Header(...)):
    # Extract token from header
    if not Authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = Authorization.split(" ", 1)[1]
    try:
        payload = decode_jwt(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token")
        username = payload.get("sub")
        role = payload.get("role", "anonymous")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except ValueError:
        logger.exception("Error refreshing access token")
        raise HTTPException(status_code=500, detail="Internal server error")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    # Issue new token
    to_encode = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=ALGORITHM)
    return {"access_token": encoded_jwt, "token_type": "bearer"}

@auth_router.get("/auth/users", dependencies=[Depends(require_role(["admin"]))], response_model=list[UserOut])
async def list_users():
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, username, role, groups, oauth_provider, oauth_sub FROM users")
    return [UserOut(id=row["id"], username=row["username"], role=row["role"], groups=row["groups"] or '', oauth_provider=row["oauth_provider"], oauth_sub=row["oauth_sub"]) for row in rows]

@auth_router.post("/auth/users/{username}/role", dependencies=[Depends(require_role(["admin"]))])
async def update_user_role(username: str, req: RoleUpdateRequest, Authorization: str = Header(...)):
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id, username, role FROM users WHERE username = $1", username)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        old_role = user["role"]
        await conn.execute("UPDATE users SET role = $1 WHERE username = $2", req.role, username)
        # Audit log
        actor = get_actor_from_token(Authorization)
        payload = json.dumps({"username": username, "old_role": old_role, "new_role": req.role})
        payload_sha256 = hashlib.sha256(payload.encode()).hexdigest()
        await conn.execute(
            "INSERT INTO audit_logs (actor, event_type, payload_sha256, details) VALUES ($1, $2, $3, $4::jsonb)",
            actor, "role_update", payload_sha256, payload
        )
    return {"status": "updated", "username": username, "old_role": old_role, "new_role": req.role}

@auth_router.post("/auth/users/{username}/groups", dependencies=[Depends(require_role(["admin"]))])
async def update_user_groups(username: str, req: GroupUpdateRequest, Authorization: str = Header(...)):
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id, username, groups FROM users WHERE username = $1", username)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        old_groups = user["groups"] or ''
        await conn.execute("UPDATE users SET groups = $1 WHERE username = $2", req.groups, username)
        # Audit log
        actor = get_actor_from_token(Authorization)
        payload = json.dumps({"username": username, "old_groups": old_groups, "new_groups": req.groups})
        payload_sha256 = hashlib.sha256(payload.encode()).hexdigest()
        await conn.execute(
            "INSERT INTO audit_logs (actor, event_type, payload_sha256, details) VALUES ($1, $2, $3, $4::jsonb)",
            actor, "group_update", payload_sha256, payload
        )
    return {"status": "updated", "username": username, "old_groups": old_groups, "new_groups": req.groups}

@auth_router.post("/auth/users/{username}/oauth", dependencies=[Depends(require_role(["admin"]))])
async def update_user_oauth(username: str, req: OAuthUpdateRequest, Authorization: str = Header(...)):
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id, username, oauth_provider, oauth_sub FROM users WHERE username = $1", username)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        old_provider, old_sub = user["oauth_provider"], user["oauth_sub"]
        await conn.execute("UPDATE users SET oauth_provider = $1, oauth_sub = $2 WHERE username = $3", req.oauth_provider, req.oauth_sub, username)
        # Audit log
        actor = get_actor_from_token(Authorization)
        payload = json.dumps({"username": username, "old_oauth_provider": old_provider, "old_oauth_sub": old_sub, "new_oauth_provider": req.oauth_provider, "new_oauth_sub": req.oauth_sub})
        payload_sha256 = hashlib.sha256(payload.encode()).hexdigest()
        await conn.execute(
            "INSERT INTO audit_logs (actor, event_type, payload_sha256, details) VALUES ($1, $2, $3, $4::jsonb)",
            actor, "oauth_update", payload_sha256, payload
        )
    return {"status": "updated", "username": username, "oauth_provider": req.oauth_provider, "oauth_sub": req.oauth_sub}

@auth_router.delete("/auth/users/{username}", dependencies=[Depends(require_role(["admin"]))])
async def delete_user(username: str, Authorization: str = Header(...)):
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id, username FROM users WHERE username = $1", username)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        await conn.execute("DELETE FROM users WHERE username = $1", username)
        # Audit log
        actor = get_actor_from_token(Authorization)
        payload = json.dumps({"username": username})
        payload_sha256 = hashlib.sha256(payload.encode()).hexdigest()
        await conn.execute(
            "INSERT INTO audit_logs (actor, event_type, payload_sha256, details) VALUES ($1, $2, $3, $4::jsonb)",
            actor, "user_delete", payload_sha256, payload
        )
    return {"status": "deleted", "username": username}

@auth_router.get("/auth/me", response_model=UserOut)
async def get_me(request: Request):
    # JWT token required for identity (not spoofable)
    auth_header = request.headers.get("authorization", "")
    email = None
    if auth_header.startswith("Bearer "):
        actor = get_actor_from_token(auth_header)
        if actor != "unknown":
            email = actor
    if not email:
        raise HTTPException(status_code=401, detail="Authentication required")
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id, username, role, groups, oauth_provider, oauth_sub FROM users WHERE username = $1", email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(id=user["id"], username=user["username"], role=user["role"], groups=user["groups"] or '', oauth_provider=user["oauth_provider"], oauth_sub=user["oauth_sub"])

# get_actor_from_token is now imported from cirisnode.auth.dependencies


@auth_router.get("/api/v1/auth/check-access")
async def check_access(email: str = Query(...)):
    """Check if an email is allowed to access the admin UI and return their role.
    Called by NextAuth signIn + jwt callbacks. Unauthenticated endpoint."""
    pool = await get_pg_pool()
    email_lower = email.lower().strip()

    async with pool.acquire() as conn:
        # @ciris.ai → auto-create as admin if not in users table
        if email_lower.endswith(f"@{ALLOWED_ADMIN_DOMAIN}"):
            user = await conn.fetchrow(
                "SELECT id, username, role FROM users WHERE username = $1", email_lower
            )
            if not user:
                await conn.execute(
                    "INSERT INTO users (username, password, role) VALUES ($1, '', 'admin')",
                    email_lower,
                )
                return {"allowed": True, "role": "admin", "email": email_lower}
            return {"allowed": True, "role": user["role"], "email": email_lower}

        # Non-ciris.ai email → must exist in users table with non-anonymous role
        user = await conn.fetchrow(
            "SELECT id, username, role FROM users WHERE username = $1", email_lower
        )
    if user and user["role"] not in ("anonymous",):
        return {"allowed": True, "role": user["role"], "email": email_lower}

    return {"allowed": False, "role": "anonymous", "email": email_lower}


@auth_router.post("/api/v1/admin/users/invite", dependencies=[Depends(require_role(["admin"]))])
async def invite_user(req: InviteRequest, Authorization: str = Header(...)):
    """Invite an external user as a wise authority (or admin). Admin-only."""
    pool = await get_pg_pool()
    email_lower = req.email.lower().strip()

    async with pool.acquire() as conn:
        # Check if user already exists
        existing = await conn.fetchrow(
            "SELECT id, username, role FROM users WHERE username = $1", email_lower
        )
        if existing:
            raise HTTPException(status_code=409, detail="User already exists")

        valid_roles = ("wise_authority", "admin")
        role = req.role if req.role in valid_roles else "wise_authority"

        # Create user and get the new id
        user_id = await conn.fetchval(
            "INSERT INTO users (username, password, role) VALUES ($1, '', $2) RETURNING id",
            email_lower, role,
        )

        # Create authority profile
        expertise = json.dumps(req.expertise_domains or [])
        agents = json.dumps(req.assigned_agent_ids or [])
        await conn.execute(
            "INSERT INTO authority_profiles (user_id, expertise_domains, assigned_agent_ids) VALUES ($1, $2, $3)",
            user_id, expertise, agents,
        )

        # Audit log
        actor = get_actor_from_token(Authorization)
        payload = json.dumps({"email": email_lower, "role": role})
        payload_sha256 = hashlib.sha256(payload.encode()).hexdigest()
        await conn.execute(
            "INSERT INTO audit_logs (actor, event_type, payload_sha256, details) VALUES ($1, $2, $3, $4::jsonb)",
            actor, "user_invite", payload_sha256, payload,
        )

    return {
        "status": "invited",
        "email": email_lower,
        "role": role,
        "user_id": user_id,
    }
