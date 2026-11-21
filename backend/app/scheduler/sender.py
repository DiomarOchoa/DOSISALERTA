"""Envio de avisos del motor (Fase 5, Etapa 2: sender simulado).

El scheduler no sabe como se envia un aviso: solo conoce el
protocolo :class:`Sender`. En esta etapa el unico sender es
:class:`SimulatedSender`, que registra la entrega en memoria y
no toca Telegram. El envio real (Etapa 3) implementara el mismo
protocolo con python-telegram-bot y devolvera el
``telegram_message_id`` que exige D18.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

__all__ = ["SendResult", "Sender", "SimulatedSender"]


@dataclass
class SendResult:
    """Resultado de un intento de envio."""

    ok: bool
    telegram_message_id: int | None = None
    error: str | None = None
    simulated: bool = False


class Sender(Protocol):
    """Protocolo de envio: un intento por recordatorio reclamado."""

    async def send(
        self, *, reminder_id: int, user_id: int, scheduled_at: datetime
    ) -> SendResult: ...


@dataclass
class SimulatedSender:
    """Sender de pruebas: anota la entrega y no envia nada.

    ``deliveries`` guarda un registro por envio simulado, para
    que las pruebas comprueben que el envio solo ocurre tras una
    reclamacion exitosa. Nunca devuelve un ``telegram_message_id``:
    inventarlo seria aparentar una confirmacion que no existe (D18).
    """

    deliveries: list[dict] = field(default_factory=list)

    async def send(
        self, *, reminder_id: int, user_id: int, scheduled_at: datetime
    ) -> SendResult:
        self.deliveries.append(
            {
                "reminder_id": reminder_id,
                "user_id": user_id,
                "scheduled_at": scheduled_at,
            }
        )
        return SendResult(ok=True, simulated=True)
