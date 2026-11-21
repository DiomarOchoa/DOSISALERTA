"""Envio de avisos del motor (Fase 5, Etapas 2-3).

El scheduler no sabe como se envia un aviso: solo conoce el
protocolo :class:`Sender`, que recibe un :class:`SendPayload`
(remitente ya resuelto: ``chat_id`` y texto) y devuelve un
:class:`SendResult`. Hay dos implementaciones:

- :class:`TelegramSender` (Etapa 3, ``telegram_sender.py``):
  envio real con python-telegram-bot.
- :class:`SimulatedSender`: doble de pruebas. Registra la
  entrega en memoria y **nunca** devuelve un
  ``telegram_message_id``: un envio simulado no es una entrega
  real y el scheduler no lo marca ENVIADA ni lo registra en
  ``notification_logs`` (aislamiento aprobado 2026-11-20).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

__all__ = ["SendPayload", "SendResult", "Sender", "SimulatedSender"]


@dataclass(frozen=True)
class SendPayload:
    """Lo que necesita un sender para enviar un aviso."""

    reminder_id: int
    user_id: int
    chat_id: int
    text: str
    scheduled_at: datetime


@dataclass
class SendResult:
    """Resultado de un intento de envio."""

    ok: bool
    telegram_message_id: int | None = None
    error: str | None = None
    simulated: bool = False
    # "ok" | "clear" | "ambiguous" | "rate_limited" | "simulated"
    kind: str = "ok"
    retry_after_seconds: int | None = None


class Sender(Protocol):
    """Protocolo de envio: un intento por recordatorio reclamado."""

    async def send(self, payload: SendPayload) -> SendResult: ...


@dataclass
class SimulatedSender:
    """Sender de pruebas: anota la entrega y no envia nada.

    ``deliveries`` guarda un registro por envio simulado, para
    que las pruebas comprueben que el envio solo ocurre tras una
    reclamacion exitosa. Nunca devuelve un ``telegram_message_id``:
    inventarlo seria aparentar una confirmacion que no existe (D18).
    """

    deliveries: list[dict] = field(default_factory=list)

    async def send(self, payload: SendPayload) -> SendResult:
        self.deliveries.append(
            {
                "reminder_id": payload.reminder_id,
                "user_id": payload.user_id,
                "chat_id": payload.chat_id,
                "text": payload.text,
                "scheduled_at": payload.scheduled_at,
            }
        )
        return SendResult(ok=True, simulated=True, kind="simulated")
