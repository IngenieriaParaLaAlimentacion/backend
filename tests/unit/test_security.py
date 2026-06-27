import re
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_password_recovery_token,
    create_refresh_token,
    decode_token,
    encode_refresh_token,
    hash_password,
    verify_password,
)
from app.models import UserRole


def test_hash_and_verify_password():
    pw = "supersecret123"
    hashed = hash_password(pw)
    assert isinstance(hashed, str)
    assert verify_password(pw, hashed)
    assert not verify_password("wrong", hashed)


def test_create_access_token_and_decode():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert isinstance(token, str)
    decoded = decode_token(token)
    assert decoded["sub"] == str(user_id)
    assert decoded["type"] == "access"


def test_encode_and_create_refresh_token():
    token, token_hash = create_refresh_token()
    assert isinstance(token, str)
    assert isinstance(token_hash, str)
    assert re.match(r"^[a-zA-Z0-9\-_]+$", token)
    assert len(token_hash) == 64
    assert encode_refresh_token(token) == token_hash


def test_create_password_recovery_token():
    token, token_hash = create_password_recovery_token()
    assert isinstance(token, str)
    assert isinstance(token_hash, str)
    assert len(token_hash) == 64


def test_decode_token_invalid():
    assert decode_token("invalid.token") is None


def test_decode_token_expired():
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "iat": int((now - timedelta(hours=1)).timestamp()),
        "exp": int((now - timedelta(minutes=1)).timestamp()),
        "role": UserRole.FIELD_WORKER,
        "type": "access",
    }
    expired_token = jwt.encode(
        payload, settings.jwt_secret_field_worker, algorithm=settings.jwt_algorithm
    )
    assert decode_token(expired_token) is None


def test_decode_token_tampered():
    token = create_access_token(uuid.uuid4())
    header, payload, _ = token.split(".")
    tampered = f"{header}.{payload}.invalidsignature"
    assert decode_token(tampered) is None


def test_decode_token_wrong_role():
    token = create_access_token(uuid.uuid4(), role=UserRole.ADMIN)
    assert decode_token(token, expected_role=UserRole.FIELD_WORKER) is None
