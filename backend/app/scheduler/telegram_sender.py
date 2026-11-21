"""Envio real a Telegram (Fase 5, Etapa 3).

``TelegramSender`` envuelve un ``telegram.Bot`` de
python-telegram-bot y traduce cada llamada a ``SendResult``:

- Exito: ``ok=True`` con el ``telegram_message_id`` que devuelve
  Telegram (la unica confirmacion que existe).
- ``RetryAfter`` (429): fallo con el ``retry_after`` exacto de
  Telegram, sin tope.
- ``TimedOut`` / ``NetworkError``: ambiguo (la respuesta se
  perdio; no se sabe si el mensaje salio).
- Otro ``TelegramError`` (400, 403, ...): fallo claro.
- Sin ``message_id`` en la respuesta: ambiguo (no hay
  confirmacion que registrar).

El texto del aviso sigue el formato del spec §3.1 (medicamento,
dosis, hora en la zona del usuario, tratamiento) y **no lleva
botones**: los botones YA LO TOMÉ / RECORDARME DESPUÉS necesitan
los manejadores de la Fase 6; enviarlos ahora dejaría botones
muertos.

El Bot se inyecta por constructor (asi las pruebas pasan un
doble sin tocar la red) y ``from_config()`` construye el Bot
real desde ``BotConfig``. El token nunca se imprime ni se
registra.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from telegram import Bot
from telegram.error import (
    BadRequest,
    Forbidden,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)

from app.bot.config import BotConfig
from app.scheduler.sender import SendPayload, SendResult

__all__ = ["TelegramSender", "build_reminder_text", "day_label"]

logger = logging.getLogger(__name__)


def day_label(when: date, today: date) -> str:
    """'Hoy', 'Mañana' o la fecha, en la zona del usuario."""
    if when == today:
        return "Hoy"
    if when == today.fromordinal(today.toordinal() + 1):
        return "Mañana"
    return when.strftime("%d/%m/%Y")


def build_reminder_text(
    *,
    medication_name: str,
    dose_amount: Decimal,
    dose_unit: str,
    concentration: str | None,
    treatment_title: str,
    scheduled_at: datetime,
    user_timezone: str,
) -> str:
    """Texto del aviso (spec §3.1)."""
    tz = ZoneInfo(user_timezone)
    local = scheduled_at.astimezone(tz)
    # normalize(): la dosis llega de Numeric(10,3) como 500.000;
    # con 'f' queda "500" (y 2.5 sigue siendo "2.5").
    dose = f"{dose_amount.normalize():f} {dose_unit}"
    if concentration:
        medication_line = f"{medication_name} {concentration} — {dose}"
    else:
        medication_line = f"{medication_name} {dose}"
    return (
        "🔔 Es hora de su medicamento\n"
        f"\n💊 {medication_line}"
        f"\n🕐 {day_label(local.date(), datetime.now(tz).date())}, {local.strftime('%H:%M')}"
        f"\n📋 Tratamiento: {treatment_title}"
    )


@dataclass
class TelegramSender:
    """Envia avisos con python-telegram-bot."""

    _bot: object

    @classmethod
    def from_config(cls) -> "TelegramSender":
        """Construye el sender con el Bot real (``BotConfig``).

        Lanza ``RuntimeError`` si no hay token configurado
        (``BotConfig.require_token()``). Construir el Bot no toca
        la red: la primera llamada es el primer envio.
        """
        token = BotConfig.from_env().require_token()
        return cls(Bot(token=token))

    async def send(self, payload: SendPayload) -> SendResult:
        try:
            message = await self._bot.send_message(
                chat_id=payload.chat_id, text=payload.text
            )
        except RetryAfter as exc:
            return SendResult(
                ok=False,
                kind="rate_limited",
                retry_after_seconds=exc.retry_after,
                error=f"RetryAfter: {exc.retry_after}s",
            )
        # OJO: en python-telegram-bot, BadRequest y Forbidden son
        # subclases de NetworkError, asi que hay que atraparlas
        # ANTES: un 400/403 es un fallo claro, no ambiguo.
        except (BadRequest, Forbidden) as exc:
            return SendResult(
                ok=False,
                kind="clear",
                error=f"{type(exc).__name__}: {exc}",
            )
        except (TimedOut, NetworkError) as exc:
            return SendResult(
                ok=False,
                kind="ambiguous",
                error=f"{type(exc).__name__}: {exc}",
            )
        except TelegramError as exc:
            return SendResult(
                ok=False,
                kind="clear",
                error=f"{type(exc).__name__}: {exc}",
            )
        message_id = getattr(message, "message_id", None)
        if message is None or message_id is None:
            return SendResult(
                ok=False,
                kind="ambiguous",
                error="sin message_id en la respuesta",
            )
        return SendResult(
            ok=True, kind="ok", telegram_message_id=message_id
        )
