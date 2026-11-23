"""Vinculacion de la cuenta de Telegram del paciente (Etapa 6, RF15).

Implementa el diseno de `docs/ESPECIFICACION_BOT_TELEGRAM.md` §5.2
y `docs/database/MODELO_DATOS.md` §3.8 y §7.3:

- El paciente genera un codigo de un solo uso desde la web
  (POST /telegram/link): 10 caracteres, alfabeto de 32 sin
  confusiones, `secrets`, HMAC-SHA256 con el secreto independiente
  `TELEGRAM_LINK_SECRET`, expiracion 15 minutos. Solo se guarda el
  HMAC; el codigo en texto plano nunca se guarda, nunca va en logs
  y solo se devuelve una vez, en la respuesta de creacion.
- El paciente entrega el codigo al bot (`/vincular CODIGO`): el
  servicio valida el codigo, la expiracion y el limite de intentos
  (5 fallos por `chat_id` en 15 minutos, `telegram_link_attempts`),
  y vincula la identidad de Telegram a la cuenta (estado
  VINCULADA, `chat_id`, `telegram_user_id`, `linked_at`). Al
  vincular, el hash y la expiracion pasan a NULL en la misma
  transaccion que cambia el estado.
- Desvinculacion desde la web (POST /telegram/unlink): el vinculo
  pasa a REVOCADA y el hash y la expiracion pasan a NULL; el
  scheduler deja de enviar avisos a ese `chat_id` y el bot deja
  de responder a sus consultas (RF19).

Los errores de codigo son genericos a proposito (404 "Codigo no
valido o expirado"): un codigo inexistente, vencido, ya usado o
bloqueado devuelven lo mismo, para no confirmar que codigos
existen. Cada intento queda en `telegram_link_attempts` (exito o
fallo, con motivo), incluso los de codigos inexistentes: sin esa
tabla, el limite por `chat_id` dependeria de memoria que se
pierde al reiniciar el bot.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.telegram import TelegramAccount, TelegramLinkAttempt
from app.models.users import User
from app.schemas.telegram_link import (
    TelegramLinkCodeResponse,
    TelegramLinkStatusResponse,
)

# Alfabeto de 32 caracteres sin confusiones (sin I, O, 0 ni 1):
# 24 letras + 8 digitos = 50 bits por codigo de 10 caracteres.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 10
_CODE_TTL = timedelta(minutes=15)
_MAX_FAILED_ATTEMPTS = 5
_RATE_LIMIT_WINDOW = timedelta(minutes=15)

_GENERIC_CODE_ERROR = "Código no válido o expirado"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _generate_code() -> str:
    """Codigo de vinculacion de 10 caracteres, con `secrets`."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def _code_hash(code: str) -> str:
    """HMAC-SHA256 del codigo con el secreto de Telegram."""
    secret = get_settings().telegram_link_secret.encode("utf-8")
    return hmac.new(secret, code.encode("utf-8"), hashlib.sha256).hexdigest()


def _status_response(account: TelegramAccount | None) -> TelegramLinkStatusResponse:
    """Estado de vinculacion del usuario (sin exponer el codigo)."""
    if account is None:
        return TelegramLinkStatusResponse(
            status="SIN_VINCULAR",
            telegram_username=None,
            linked_at=None,
            has_pending_code=False,
        )
    return TelegramLinkStatusResponse(
        status=account.status,
        telegram_username=account.username,
        linked_at=account.linked_at,
        has_pending_code=account.link_code_hash is not None,
    )


async def _record_attempt(
    session: AsyncSession,
    *,
    chat_id: int,
    telegram_user_id: int | None,
    attempted_code_hash: str | None,
    success: bool,
    reason: str | None,
) -> None:
    """Registra un intento de vinculacion y lo confirma de inmediato.

    El intento queda guardado aunque la vinculacion falle: es una
    fila de seguridad, no de negocio. El commit inmediato hace que
    sobreviva al error generico que sigue.
    """
    session.add(
        TelegramLinkAttempt(
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            attempted_code_hash=attempted_code_hash,
            success=success,
            reason=reason,
        )
    )
    await session.commit()


async def _recent_failures(session: AsyncSession, chat_id: int) -> int:
    """Fallos de vinculacion de este chat en los ultimos 15 minutos."""
    since = _utcnow() - _RATE_LIMIT_WINDOW
    result = await session.execute(
        select(func.count())
        .select_from(TelegramLinkAttempt)
        .where(
            TelegramLinkAttempt.chat_id == chat_id,
            TelegramLinkAttempt.success.is_(False),
            TelegramLinkAttempt.attempted_at >= since,
        )
    )
    return int(result.scalar_one())


async def create_link_code(
    session: AsyncSession, user: User
) -> TelegramLinkCodeResponse:
    """Genera un codigo de vinculacion para el usuario (una sola vez).

    Crea la fila PENDIENTE si no existe; si ya existe (incluso
    REVOCADA), la reutiliza con un codigo nuevo y expiracion nueva.
    Un codigo anterior queda invalidado: solo vale el ultimo.
    """
    result = await session.execute(
        select(TelegramAccount).where(TelegramAccount.user_id == user.id)
    )
    account = result.scalar_one_or_none()
    code = _generate_code()
    expires_at = _utcnow() + _CODE_TTL
    if account is None:
        account = TelegramAccount(
            user_id=user.id,
            status="PENDIENTE",
            link_code_hash=_code_hash(code),
            link_expires_at=expires_at,
        )
        session.add(account)
    else:
        account.status = "PENDIENTE"
        account.link_code_hash = _code_hash(code)
        account.link_expires_at = expires_at
        # La identidad anterior queda sin efecto hasta que el nuevo
        # codigo se confirme: un chat viejo no puede seguir usando
        # el vinculo con un codigo nuevo pendiente.
        account.telegram_user_id = None
        account.chat_id = None
        account.username = None
        account.linked_at = None
    await session.commit()
    return TelegramLinkCodeResponse(code=code, expires_at=expires_at)


async def confirm_link(
    session: AsyncSession,
    code: str,
    telegram_user_id: int,
    chat_id: int,
    username: str | None = None,
) -> TelegramAccount:
    """Vincula la identidad de Telegram con el codigo (bot /vincular).

    El codigo se normaliza a mayusculas (el alfabeto es solo
    mayusculas y digitos). Cualquier fallo devuelve el mismo error
    generico 404 y queda registrado en `telegram_link_attempts`.
    """
    normalized = code.strip().upper()
    attempted_hash = _code_hash(normalized)

    # Limite por chat: 5 fallos en 15 minutos bloquean el chat.
    if await _recent_failures(session, chat_id) >= _MAX_FAILED_ATTEMPTS:
        await _record_attempt(
            session,
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            attempted_code_hash=attempted_hash,
            success=False,
            reason="LIMITADO",
        )
        raise HTTPException(status_code=404, detail=_GENERIC_CODE_ERROR)

    result = await session.execute(
        select(TelegramAccount).where(
            TelegramAccount.link_code_hash == attempted_hash,
            TelegramAccount.status == "PENDIENTE",
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        await _record_attempt(
            session,
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            attempted_code_hash=attempted_hash,
            success=False,
            reason="INVALIDO",
        )
        raise HTTPException(status_code=404, detail=_GENERIC_CODE_ERROR)

    now = _utcnow()
    if account.link_expires_at is None or account.link_expires_at <= now:
        await _record_attempt(
            session,
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            attempted_code_hash=attempted_hash,
            success=False,
            reason="VENCIDO",
        )
        raise HTTPException(status_code=404, detail=_GENERIC_CODE_ERROR)

    # Un telegram_user_id ya vinculado a otro usuario no puede
    # vincularse de nuevo: el indice unico parcial lo impediria,
    # pero el error generico no revela el motivo.
    taken = await session.execute(
        select(TelegramAccount.id).where(
            TelegramAccount.telegram_user_id == telegram_user_id,
            TelegramAccount.status == "VINCULADA",
            TelegramAccount.user_id != account.user_id,
        )
    )
    if taken.scalar_one_or_none() is not None:
        await _record_attempt(
            session,
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            attempted_code_hash=attempted_hash,
            success=False,
            reason="INVALIDO",
        )
        raise HTTPException(status_code=404, detail=_GENERIC_CODE_ERROR)

    account.status = "VINCULADA"
    account.telegram_user_id = telegram_user_id
    account.chat_id = chat_id
    account.username = username
    account.linked_at = now
    account.link_code_hash = None
    account.link_expires_at = None
    await _record_attempt(
        session,
        chat_id=chat_id,
        telegram_user_id=telegram_user_id,
        attempted_code_hash=None,
        success=True,
        reason=None,
    )
    return account


async def unlink(session: AsyncSession, user: User) -> TelegramAccount | None:
    """Desvincula Telegram del usuario (desde la web).

    El vinculo pasa a REVOCADA y el hash y la expiracion pasan a
    NULL en la misma transaccion. Sin cuenta, no hay nada que
    desvincular (se devuelve None).
    """
    result = await session.execute(
        select(TelegramAccount).where(TelegramAccount.user_id == user.id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        return None
    account.status = "REVOCADA"
    account.link_code_hash = None
    account.link_expires_at = None
    await session.commit()
    return account


async def get_status(session: AsyncSession, user: User) -> TelegramLinkStatusResponse:
    """Estado de vinculacion de Telegram del usuario."""
    result = await session.execute(
        select(TelegramAccount).where(TelegramAccount.user_id == user.id)
    )
    return _status_response(result.scalar_one_or_none())
