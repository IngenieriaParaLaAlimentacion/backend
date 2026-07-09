import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import settings
from app.models import UserRole

_password_hasher = PasswordHasher()


def _get_secret(role: str) -> str:
    return {
        "superadmin": settings.jwt_secret_admin,
        "admin": settings.jwt_secret_admin,
        "analyst": settings.jwt_secret_analyst,
        "field_worker": settings.jwt_secret_field_worker,
    }.get(role, settings.jwt_secret_field_worker)


def hash_password(password: str) -> str:
    """Hash a plain password for secure storage."""
    return _password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plain password against its stored hash."""
    try:
        _password_hasher.verify(hashed, password)
        return True
    except VerifyMismatchError:
        return False


def create_access_token(user_id, role: str = UserRole.FIELD_WORKER):
    """Create a signed access JWT for a user identifier."""
    secret = _get_secret(role)
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "role": role,
        "exp": int(
            (now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()
        ),
        "type": "access",
    }

    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_role: str = UserRole.FIELD_WORKER):
    """Decode and validate a JWT, returning None on failure."""
    secret = _get_secret(expected_role)
    try:
        return jwt.decode(token, secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def hash_token(token: str) -> str:
    """Encode a refresh token string as a SHA-256 hash."""
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_token_pair(nbytes: int = 64) -> tuple[str, str]:
    """Private base generator to create a secure token and its SHA-256 hash."""
    token = secrets.token_urlsafe(nbytes)
    return token, hash_token(token)


def create_refresh_token():
    """Create a random refresh token and its SHA-256 hash."""
    return _generate_token_pair(nbytes=64)


def create_password_recovery_token() -> tuple[str, str]:
    """Create a random password recovery token and its SHA-256 hash."""
    return _generate_token_pair(nbytes=64)


def create_email_verification_token() -> tuple[str, str]:
    """Create a random email verification token and its SHA-256 hash."""
    return _generate_token_pair(nbytes=64)
