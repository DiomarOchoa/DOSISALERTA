"""Tablas ``telegram_accounts`` y ``telegram_link_attempts``
(`docs/database/MODELO_DATOS.md` §3.8 y §3.11).

- ``telegram_accounts``: un vinculo por usuario en v1. El codigo de
  vinculacion solo existe como HMAC-SHA256 con ``TELEGRAM_LINK_SECRET``;
  al vincular, expirar o revocar, el hash y la expiracion pasan a NULL
  en la misma transaccion que cambia el estado (MODELO_DATOS §7.3).
- ``telegram_link_attempts``: tabla de seguridad, no de negocio. Sin
  ella, el limite de intentos por ``chat_id`` dependeria de memoria
  que se pierde al reiniciar el bot.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.users import User

# Estados de una cuenta de Telegram vinculada (MODELO_DATOS §3.8).
TELEGRAM_ACCOUNT_STATUSES = ("PENDIENTE", "VINCULADA", "REVOCADA")


class TelegramAccount(Base):
    """Cuenta de Telegram vinculada a un usuario."""

    __tablename__ = "telegram_accounts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDIENTE', 'VINCULADA', 'REVOCADA')",
            name="ck_telegram_accounts_status",
        ),
        Index(
            "uq_telegram_user",
            "telegram_user_id",
            unique=True,
            postgresql_where="telegram_user_id IS NOT NULL",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, unique=True
    )
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    link_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    link_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDIENTE"
    )
    linked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="telegram_account")


class TelegramLinkAttempt(Base):
    """Intento de vinculacion de Telegram (antifraude).

    Sin FK a users: se registra por ``chat_id``, incluso para
    intentos de chats no vinculados.
    """

    __tablename__ = "telegram_link_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attempted_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reason: Mapped[str | None] = mapped_column(String(50), nullable=True)


# Indice (chat_id, attempted_at DESC) para el limite de intentos
# (MODELO_DATOS §5): se define aqui porque __table_args__ no admite
# el orden DESC con nombres de columna en texto.
Index(
    "idx_link_attempts_chat",
    TelegramLinkAttempt.__table__.c.chat_id,
    TelegramLinkAttempt.__table__.c.attempted_at.desc(),
)
