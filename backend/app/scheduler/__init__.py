"""Motor de recordatorios (Fase 5).

El scheduler vive aqui: :class:`ReminderScheduler` ordena los
PENDIENTE en el ReminderHeap y los reclama de forma atomica en
PostgreSQL antes de enviarlos. El envio de esta etapa es
simulado (:class:`SimulatedSender`); el envio real llega en la
Etapa 3.
"""

from app.scheduler.scheduler import ReminderScheduler
from app.scheduler.sender import SendResult, Sender, SimulatedSender

__all__ = [
    "ReminderScheduler",
    "SendResult",
    "Sender",
    "SimulatedSender",
]
