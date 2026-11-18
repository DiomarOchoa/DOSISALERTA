"""Pruebas unitarias de `app.core.security` (Fase 3).

Funciones puras: no levantan la aplicacion ni tocan la base de
datos. El secreto JWT de prueba lo fija `conftest.py`.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core import security
from app.core.config import get_settings
from app.models.users import User


def _make_user(user_id: int = 42) -> User:
    """Usuario sin persistir, solo para generar el JWT."""
    return User(
        id=user_id,
        name="Prueba",
        email="prueba@example.com",
        password_hash="hash",
    )


# ------------------------------------------------------------------
# Hash de contrasenas (bcrypt)
# ------------------------------------------------------------------


def test_hash_password_no_guarda_en_claro():
    """El hash no es la contrasena y empieza por $2b$."""
    hashed = security.hash_password("clave-segura-123")
    assert hashed != "clave-segura-123"
    assert hashed.startswith("$2b$")
    assert len(hashed) == 60


def test_hash_password_es_diferente_cada_vez():
    """Dos hashes de la misma contrasena son distintos (salt aleatorio)."""
    first = security.hash_password("clave-segura-123")
    second = security.hash_password("clave-segura-123")
    assert first != second


def test_verify_password_correcta():
    """verify_password devuelve True con la contrasena correcta."""
    hashed = security.hash_password("clave-segura-123")
    assert security.verify_password("clave-segura-123", hashed) is True


def test_verify_password_incorrecta():
    """verify_password devuelve False con una contrasena incorrecta."""
    hashed = security.hash_password("clave-segura-123")
    assert security.verify_password("otra-clave-456", hashed) is False


def test_verify_password_hash_invalido():
    """Un hash guardado sin formato bcrypt devuelve False, no lanza."""
    assert security.verify_password("clave-segura-123", "esto-no-es-un-hash") is False


def test_verify_password_demasiado_larga_no_lanza():
    """Una contrasena de mas de 72 bytes devuelve False, no lanza.

    `bcrypt.checkpw` lanzaria ValueError; se captura (ver §4.1).
    Nunca provoca un 500.
    """
    hashed = security.hash_password("clave-segura-123")
    long_password = "x" * 100
    assert security.verify_password(long_password, hashed) is False


# ------------------------------------------------------------------
# Access token (JWT)
# ------------------------------------------------------------------


def test_create_access_token_es_jwt_valido():
    """El token se decodifica; sub es el id (string), type access, exp ~60 min."""
    settings = get_settings()
    token = security.create_access_token(_make_user(user_id=42))
    payload = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    assert payload["sub"] == "42"
    assert payload["email"] == "prueba@example.com"
    assert payload["type"] == "access"
    assert payload["exp"] - payload["iat"] == 60 * 60


def test_decode_access_token_rechaza_otro_secreto():
    """Un token firmado con otro secreto se rechaza."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    other = jwt.encode(
        {
            "sub": "42",
            "email": "prueba@example.com",
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        "otro-secreto-completamente-distinto-0123456789",
        algorithm="HS256",
    )
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(other)


def test_decode_access_token_rechaza_expirado():
    """Un token con exp pasado se rechaza."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {
            "sub": "42",
            "email": "prueba@example.com",
            "type": "access",
            "iat": now - timedelta(minutes=120),
            "exp": now - timedelta(minutes=60),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(expired)


def test_decode_access_token_rechaza_otro_tipo():
    """Un token con type distinto de "access" se rechaza."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    other_type = jwt.encode(
        {
            "sub": "42",
            "email": "prueba@example.com",
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(other_type)


# ------------------------------------------------------------------
# Refresh token (opaco, hash SHA-256)
# ------------------------------------------------------------------


def test_hash_refresh_token_es_sha256():
    """El hash es un hex de 64 caracteres (SHA-256), distinto del token."""
    raw = security.generate_refresh_token()
    hashed = security.hash_refresh_token(raw)
    assert len(hashed) == 64
    assert all(c in "0123456789abcdef" for c in hashed)
    assert hashed != raw


def test_generate_refresh_token_es_aleatorio():
    """Dos tokens generados son distintos."""
    first = security.generate_refresh_token()
    second = security.generate_refresh_token()
    assert first != second
