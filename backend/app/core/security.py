"""Seguridad de autenticacion: hash de contrasenas y tokens JWT (Fase 3).

Funciones puras, sin FastAPI ni SQLAlchemy: se pueden probar por
separado sin levantar la aplicacion ni la base de datos.

- Contraseñas: bcrypt (`hashpw`, `gensalt`, `checkpw`), coste 12.
  Nunca se guarda ni se devuelve la contrasena en claro.
- Access token: JWT HS256 con PyJWT. Autocontenido, no se guarda
  en la base de datos. Expira a los `JWT_ACCESS_EXPIRATION_MINUTES`
  (60 por defecto).
- Refresh token: valor opaco aleatorio (`secrets.token_urlsafe(32)`).
  Solo se guarda su hash SHA-256 en `refresh_tokens`, nunca en claro.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import bcrypt
import jwt

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.models.users import User


class InvalidTokenError(Exception):
    """El access token es invalido, expiro o no es de tipo access.

    `deps.py` la convierte en 401. Nunca lleva el token en el mensaje.
    """


def hash_password(plain: str) -> str:
    """Hashea una contrasena con bcrypt (coste 12, salt aleatorio).

    Devuelve el hash como texto (empieza por ``$2b$``, 60 caracteres),
    que se guarda en ``users.password_hash``.
    """
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Comprueba una contrasena contra su hash bcrypt.

    Devuelve False si no coincide. Si el hash guardado no tiene
    formato bcrypt valido, o si la contrasena supera los 72 bytes,
    `bcrypt.checkpw` lanza `ValueError`; se captura y se devuelve
    False (red de seguridad: la validacion de Pydantic ya rechaza
    esas contrasenas con 422 antes de llegar aqui). Nunca se propaga
    la excepcion y nunca provoca un 500.
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user: User) -> str:
    """Crea un access token JWT (HS256) para un usuario.

    Claims: `sub` (id del usuario como string), `email`, `type`
    ("access"), `iat` y `exp` (ahora + `JWT_ACCESS_EXPIRATION_MINUTES`).
    El token NO se guarda en la base de datos.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_expiration_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decodifica y valida un access token JWT.

    Valida firma, algoritmo (solo HS256, nunca `none` ni otro) y
    expiracion, y exige `type == "access"`. Si algo falla, lanza
    `InvalidTokenError` (sin incluir el token en el mensaje).
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Token inválido o expirado") from exc
    if payload.get("type") != "access":
        raise InvalidTokenError("Tipo de token no válido")
    return payload


def generate_refresh_token() -> str:
    """Genera un refresh token opaco aleatorio (32 bytes de entropia).

    No es un JWT: es un valor aleatorio que se devuelve al cliente
    una sola vez y del que solo se guarda el hash en la BD.
    """
    return secrets.token_urlsafe(32)


def hash_refresh_token(raw: str) -> str:
    """Hash SHA-256 (hex, 64 caracteres) de un refresh token.

    Solo este hash se guarda en `refresh_tokens.token_hash`.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
