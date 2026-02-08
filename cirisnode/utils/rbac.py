from fastapi import Depends, HTTPException, Header, status
import jwt
from cirisnode.config import settings

SECRET_KEY = getattr(settings, "JWT_SECRET", None) or "testsecret"
ALGORITHM = "HS256"


def get_current_role(Authorization: str = Header(...)) -> str:
    if not Authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")
    token = Authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("role", "anonymous")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def require_role(allowed_roles: list):
    def checker(role: str = Depends(get_current_role)):
        if role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return checker
