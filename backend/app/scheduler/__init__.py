"""Motor de recordatorios (Fase 5).

El scheduler vive aqui: :class:`ReminderScheduler` ordena los
PENDIENTE en el ReminderHeap y los reclama de forma atomica en
PostgreSQL antes de enviarlos. El envio real es
:class:`TelegramSender`; el envio simulado
(:class:`SimulatedSender`) solo existe en las pruebas y nunca
marca ENVIADA.
"""

from app.scheduler.retry_policy import (
    AMBIGUOUS_DELAY,
    CLEAR_FAILURE_DELAYS,
    MAX_ATTEMPTS,
    RetryDecision,
    decide,
)
from app.scheduler.reconciliation import ReconcileResult, Reconciler
from app.scheduler.scheduler import ReminderScheduler
from app.scheduler.sender import (
    SendPayload,
    SendResult,
    Sender,
    SimulatedSender,
)
from app.scheduler.telegram_sender import TelegramSender, build_reminder_text
from app.scheduler.topup import TopUpResult, run_topup

__all__ = [
    "ReminderScheduler",
    "Reconciler",
    "ReconcileResult",
    "TopUpResult",
    "run_topup",
    "SendPayload",
    "SendResult",
    "Sender",
    "SimulatedSender",
    "TelegramSender",
    "build_reminder_text",
    "RetryDecision",
    "decide",
    "MAX_ATTEMPTS",
    "CLEAR_FAILURE_DELAYS",
    "AMBIGUOUS_DELAY",
]
