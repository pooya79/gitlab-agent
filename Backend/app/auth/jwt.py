import datetime as dt
import secrets
import hashlib
import uuid
import jwt

from app.core.config import settings
from app.core.time import utc_now


def create_access_token(user_id: str, jti: str, is_admin: bool = False) -> str:
    """Create a JWT access token.

    Set ``is_admin=True`` to mint a token for the separate admin realm
    (validated by ``get_current_admin``).
    """
    now = utc_now()
    payload = {
        "sub": user_id,
        "jti": jti,
        "is_admin": is_admin,
        "iat": now,
        "nbf": now,
        "exp": now + dt.timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """Generate a new secure refresh token."""
    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)
    return token, token_hash


def create_jti() -> str:
    return str(uuid.uuid4())


def decode_token(token: str) -> dict:
    """Decode a JWT token and return its payload."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
