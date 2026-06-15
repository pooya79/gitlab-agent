"""Password hashing helpers for admin (username/password) authentication.

Uses the ``bcrypt`` library directly — passlib 1.7.x is incompatible with
bcrypt >= 4.1 (it fails reading the removed ``__about__`` version attribute).
"""

import bcrypt

# bcrypt only considers the first 72 bytes of the password.
_MAX_BYTES = 72


def _encode(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(_encode(password), password_hash.encode("utf-8"))
    except Exception:
        return False
