"""Security helpers for password hashing and JWT access token handling."""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from setrem_estagio_canis.core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    SECRET_KEY,
)


def hash_password(password: str) -> str:
    """Generate a bcrypt hash for a plain-text password.

    Args:
        password: Plain-text password string.

    Returns:
        Encoded bcrypt hash string.
    """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a stored bcrypt hash.

    Args:
        plain_password: Candidate plain-text password.
        hashed_password: Stored bcrypt hash.

    Returns:
        True if the password matches, False otherwise.
    """
    if not hashed_password:
        return False
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def create_access_token(
    data: dict[str, object],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token with expiration claim.

    Args:
        data: Claims dictionary (e.g. {'sub': '1', 'email': '...'}).
        expires_delta: Optional custom expiration duration.

    Returns:
        Encoded JWT string.
    """
    to_encode: dict[str, object] = dict(data)
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, object] | None:
    """Decode and validate a JWT access token.

    Args:
        token: Encoded JWT string.

    Returns:
        Decoded claims dictionary, or None if invalid or expired.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload if isinstance(payload, dict) else None
    except jwt.PyJWTError:
        return None
