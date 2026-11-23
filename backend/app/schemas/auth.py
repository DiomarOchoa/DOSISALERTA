"""Esquemas Pydantic de autenticacion (Fase 3).

Entrada y salida de los endpoints de `api/routers/auth.py`.
La regla de la contrasena (minimo 8 caracteres, maximo 72 bytes
UTF-8) se define una sola vez en `validate_password` y la usan
`UserRegister` y `UserLogin`, para que ambos endpoints apliquen
exactamente la misma regla.

`UserResponse` nunca incluye `password_hash`.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def validate_password(password: str) -> str:
    """Regla compartida de contrasena (registro y login).

    - Minimo 8 caracteres.
    - Maximo 72 bytes UTF-8 (medido en bytes, no en caracteres:
      bcrypt trunca por encima de 72 bytes). Una contrasena con
      caracteres multibyte puede superar los 72 bytes con menos
      de 72 caracteres.

    Se rechaza con 422 antes de llegar a bcrypt, asi una
    contrasena demasiado larga nunca provoca un 500.
    """
    if len(password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres")
    if len(password.encode("utf-8")) > 72:
        raise ValueError("La contraseña no puede superar los 72 bytes")
    return password


def _validate_name_not_blank(name: str) -> str:
    """El nombre no puede ser solo espacios en blanco."""
    if not name.strip():
        raise ValueError("El nombre no puede estar vacío")
    return name


def _validate_timezone_iana(value: str) -> str:
    """La zona horaria debe ser una zona IANA valida."""
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        raise ValueError(f"Zona horaria no válida: {value}") from None
    return value


class UserRegister(BaseModel):
    """Entrada de `POST /api/v1/auth/register`."""

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str
    timezone: str = "America/Bogota"

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _validate_name_not_blank(value)

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return validate_password(value)

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        return _validate_timezone_iana(value)


class UserUpdate(BaseModel):
    """Entrada de `PATCH /api/v1/auth/me` (RF03).

    Solo la zona horaria es actualizable por ahora. Si no se
    envia `timezone`, no se cambia nada y se devuelve el perfil
    actual. Un cambio de zona recalcula unicamente los
    recordatorios PENDIENTE futuros (RNF04).
    """

    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_timezone_iana(value)


class UserLogin(BaseModel):
    """Entrada de `POST /api/v1/auth/login` (JSON)."""

    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return validate_password(value)


class TokenRefresh(BaseModel):
    """Entrada de `POST /api/v1/auth/refresh` y `/logout`."""

    refresh_token: str = Field(min_length=1)


class UserResponse(BaseModel):
    """Perfil publico de un usuario. Nunca incluye `password_hash`."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    timezone: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """Tokens devueltos por login y refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserRegisterResponse(BaseModel):
    """Respuesta de `POST /api/v1/auth/register` (201)."""

    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
