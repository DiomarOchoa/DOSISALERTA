"""Esquemas de vinculacion de Telegram (Etapa 6, RF15)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TelegramLinkCodeResponse(BaseModel):
    """Codigo de vinculacion, devuelto UNA SOLA VEZ al crearlo."""

    code: str = Field(description="Codigo de 10 caracteres para /vincular")
    expires_at: datetime = Field(description="Expiracion (15 minutos)")


class TelegramLinkStatusResponse(BaseModel):
    """Estado de vinculacion de Telegram del usuario."""

    status: str = Field(
        description="SIN_VINCULAR, PENDIENTE, VINCULADA o REVOCADA"
    )
    telegram_username: str | None = None
    linked_at: datetime | None = None
    has_pending_code: bool = Field(
        description="True si hay un codigo pendiente sin confirmar"
    )
