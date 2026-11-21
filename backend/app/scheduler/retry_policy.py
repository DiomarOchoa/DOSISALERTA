"""Politica de reintentos del envio (Fase 5, Etapa 3).

Pura y sin E/S: dada la cuenta de intentos y el resultado del
envio, decide el siguiente estado. Los retrasos son parametros
para que las pruebas usen segundos en lugar de minutos.

- Exito con ``telegram_message_id``: ENVIADA.
- Fallo claro (la API de Telegram devuelve un error): reintento
  con backoff +1 min y +5 min; al tercer intento, FALLIDA.
- Ambiguo (la respuesta se perdio): reintento a +10 min; al
  tercer intento, FALLIDA.
- 429 (``RetryAfter``): se respeta exactamente el ``retry_after``
  de Telegram, sin tope (decision aprobada 2026-11-20).
- Maximo 3 intentos en total, sea cual sea el resultado.

Los resultados simulados nunca llegan aqui: el scheduler los
aparta antes (un envio simulado no es una entrega real y no
genera ni log ni cambio de estado).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.scheduler.sender import SendResult

__all__ = [
    "RetryDecision",
    "MAX_ATTEMPTS",
    "CLEAR_FAILURE_DELAYS",
    "AMBIGUOUS_DELAY",
    "decide",
]

MAX_ATTEMPTS = 3
CLEAR_FAILURE_DELAYS = (timedelta(minutes=1), timedelta(minutes=5))
AMBIGUOUS_DELAY = timedelta(minutes=10)


@dataclass(frozen=True)
class RetryDecision:
    """Siguiente paso tras un intento de envio."""

    action: str  # "sent" | "retry" | "failed"
    next_attempt_at: datetime | None = None


def decide(
    result: SendResult,
    *,
    attempt_count: int,
    now: datetime,
    clear_delays: tuple[timedelta, ...] = CLEAR_FAILURE_DELAYS,
    ambiguous_delay: timedelta = AMBIGUOUS_DELAY,
) -> RetryDecision:
    """Decide el siguiente estado tras un intento real.

    ``attempt_count`` es la cuenta despues de la reclamacion
    (1 para el primer intento). Un resultado simulado no debe
    llegar aqui.
    """
    if result.ok and result.telegram_message_id is not None:
        return RetryDecision("sent")
    if attempt_count >= MAX_ATTEMPTS:
        return RetryDecision("failed")
    if result.kind == "rate_limited":
        seconds = result.retry_after_seconds or 0
        return RetryDecision("retry", now + timedelta(seconds=seconds))
    if result.kind == "ambiguous":
        return RetryDecision("retry", now + ambiguous_delay)
    index = min(attempt_count - 1, len(clear_delays) - 1)
    return RetryDecision("retry", now + clear_delays[index])
