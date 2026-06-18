"""
auth.py  ─  Authentication & authorisation helpers.

Provides:
  - Password hashing / verification  (bcrypt via passlib)
  - JWT token creation / validation   (python-jose)
  - FastAPI dependency for extracting the current user from a request
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import User

load_dotenv()

# ── Configuration ────────────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me")
ALGORITHM  = os.getenv("JWT_ALGORITHM", "HS256")
EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))

# ── Password hashing context ────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── OAuth2 bearer scheme (expects "Authorization: Bearer <token>") ──
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── Password utilities ──────────────────────────────────────
def hash_password(plain: str) -> str:
    """Return the bcrypt hash of *plain*."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Check *plain* against a bcrypt *hashed* value."""
    return pwd_context.verify(plain, hashed)


# ── JWT utilities ────────────────────────────────────────────
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a signed JWT containing *data*.
    The token expires after EXPIRE_MIN minutes by default.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=EXPIRE_MIN))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


# ── FastAPI dependency: get current user from token ─────────
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Extracts user_id from the JWT, fetches the user from DB,
    and returns the ORM object.  Used as a FastAPI dependency.
    """
    payload = decode_access_token(token)
    user_id: int = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Token missing user_id")

    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_role(*allowed_roles: str):
    """
    Returns a FastAPI dependency that checks whether the current
    user's role is one of *allowed_roles*.

    Usage:
        @app.get("/lab", dependencies=[Depends(require_role("lab_staff"))])
    """
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' not authorised",
            )
        return current_user
    return role_checker
