"""Scheduler del motor de recordatorios (Fase 5, Etapa 2, D16/D18/D19).

El scheduler es el bucle del motor: carga los recordatorios
PENDIENTE desde PostgreSQL, los ordena en el ReminderHeap y,
cuando llega su hora, los reclama de forma atomica y los envia.

Reglas (D16/D18/D19):

- La base de datos es la verdad; la cola es solo una vista
  ordenada de los PENDIENTE. La cola se reconstruye desde la BD
  en cada arranque y se recarga periodicamente (los tratamientos
  creados mientras la API corre aparecen en la siguiente recarga).
- ``jobs_by_id`` / ``jobs_by_user`` son indices O(1) para
  cancelar o reprogramar sin recorrer la cola; nunca deciden un
  envio por si solos (D16).
- Solo quien reclama (PENDIENTE -> ENVIANDO con un
  ``current_attempt_id`` nuevo, en una sola transaccion) puede
  ejecutar el envio y marcar ENVIADA (D18).
- Una sola instancia de la API (D19): el scheduler corre en el
  proceso de la API. Con ``--workers > 1`` habria varios
  schedulers y la reclamacion atomica seguiria garantizando un
  unico envio, pero eso no se promete.
- Ventana de gracia (30 min): un recordatorio vencido dentro de
  la gracia se carga y se envia (la dosis todavia puede
  confirmarse); un vencido fuera de ella no se carga: queda en
  la BD para que la Etapa 5 lo marque PERDIDA.

La espera es eficiente: el bucle duerme hasta el proximo
recordatorio (o hasta la siguiente recarga, lo que llegue
antes) y se despierta antes si ``notify()`` lo llama. No hay
bucle ocupado.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms.reminder_heap import HeapJob, PriorityQueue, ReminderHeap
from app.models.reminders import MedicationReminder
from app.repositories import reminder_repository
from app.scheduler.sender import Sender

__all__ = ["ReminderScheduler"]

logger = logging.getLogger(__name__)

# Ventana de gracia del diseno: una dosis no confirmada en 30
# minutos es PERDIDA (Etapa 5). Hasta entonces, el aviso todavia
# tiene sentido y el scheduler lo envia.
GRACE_MINUTES = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReminderScheduler:
    """Bucle del motor: cola en memoria + reclamacion atomica en BD."""

    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        sender: Sender,
        *,
        queue_factory: Callable[[], PriorityQueue] = ReminderHeap,
        reload_interval_seconds: float = 60.0,
    ) -> None:
        self._session_factory = session_factory
        self._sender = sender
        self._queue = queue_factory()
        self._jobs_by_id: dict[int, tuple[HeapJob, int]] = {}
        self._jobs_by_user: dict[int, set[int]] = {}
        self._reload_interval = reload_interval_seconds
        self._wake = asyncio.Event()
        self._stopped = True
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        """True mientras el bucle esta en marcha."""
        return self._task is not None and not self._task.done()

    def __len__(self) -> int:
        return len(self._queue)

    def job_for_id(self, reminder_id: int) -> HeapJob | None:
        """El trabajo en cola con ese id, o None si no esta en cola."""
        entry = self._jobs_by_id.get(reminder_id)
        return entry[0] if entry is not None else None

    def jobs_for_user(self, user_id: int) -> set[int]:
        """Ids en cola de ese usuario (copia)."""
        return set(self._jobs_by_user.get(user_id, set()))

    # -- ciclo de vida ------------------------------------------------

    async def start(self) -> None:
        """Carga los PENDIENTE y arranca el bucle (idempotente).

        Si la BD no responde en el arranque, se arranca con la
        cola vacia y la recarga periodica la llenara cuando la BD
        vuelva: el arranque de la API no depende de la BD.
        """
        if self._task is not None:
            return
        self._stopped = False
        try:
            await self.load_pending(_utcnow())
        except Exception:
            logger.exception("Scheduler: no se pudo cargar los PENDIENTE al arrancar")
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Apagado limpio: despierta el bucle y espera a que termine."""
        task = self._task
        if task is None:
            return
        self._stopped = True
        self.notify()
        await task
        self._task = None

    def notify(self) -> None:
        """Despierta el bucle (un trabajo nuevo llego antes de tiempo)."""
        self._wake.set()

    # -- carga y proceso ----------------------------------------------

    async def load_pending(self, now: datetime) -> int:
        """(Re)carga los PENDIENTE desde la BD y los encola.

        Solo los PENDIENTE con ``scheduled_at`` dentro de la
        ventana [ahora - gracia, ...): los ENVIADA, TOMADA,
        POSPUESTA, PERDIDA, CANCELADA y FALLIDA no vuelven a la
        cola, y los vencidos fuera de la gracia quedan en la BD
        para la Etapa 5. Re-encolar un id ya en cola lo reemplaza
        (semantica de ``push``), asi que recargar es seguro.
        Devuelve cuantos se cargaron.
        """
        from_dt = now - timedelta(minutes=GRACE_MINUTES)
        async with self._session_factory() as session:
            rows = await reminder_repository.list_pending(
                session, from_dt=from_dt
            )
        count = 0
        for row in rows:
            self.add_job(HeapJob(row.scheduled_at, row.id), row.user_id)
            count += 1
        return count

    async def process_due(self, now: datetime) -> list[int]:
        """Procesa los trabajos vencidos hasta ``now``.

        Por cada trabajo vencido: lo saca de la cola y de los
        indices, lo reclama en la BD y, solo si la reclamacion
        gana, lo envia. Si el envio simulado tiene exito, marca
        ENVIADA (solo el reclamante puede: la marca exige el
        mismo ``current_attempt_id``). Si el envio falla, el
        recordatorio queda ENVIANDO y lo decide la reconciliacion
        (Etapa 5). Devuelve los ids enviados.
        """
        sent: list[int] = []
        while True:
            job = self._queue.peek()
            if job is None or job.scheduled_at > now:
                return sent
            job = self._queue.pop()
            assert job is not None
            self._drop_from_indexes(job.reminder_id)
            claimed = await self._claim(job)
            if claimed is None:
                # Otro lo reclamo, o ya no esta PENDIENTE (cancelado,
                # por ejemplo): no se envia nada.
                continue
            result = await self._sender.send(
                reminder_id=job.reminder_id,
                user_id=claimed.user_id,
                scheduled_at=job.scheduled_at,
            )
            if not result.ok:
                continue
            marked = await self._mark_sent(job, claimed)
            if marked is not None:
                sent.append(job.reminder_id)

    # -- trabajos (para el servicio de tratamientos, etapas despues) --

    def add_job(self, job: HeapJob, user_id: int) -> None:
        """Encola un trabajo y actualiza los indices (D16)."""
        self._queue.push(job)
        self._jobs_by_id[job.reminder_id] = (job, user_id)
        self._jobs_by_user.setdefault(user_id, set()).add(job.reminder_id)
        self.notify()

    def remove_job(self, reminder_id: int) -> bool:
        """Saca un trabajo de la cola y de los indices. True si estaba."""
        if not self._queue.remove(reminder_id):
            return False
        self._drop_from_indexes(reminder_id)
        return True

    def _drop_from_indexes(self, reminder_id: int) -> None:
        entry = self._jobs_by_id.pop(reminder_id, None)
        if entry is None:
            return
        user_id = entry[1]
        ids = self._jobs_by_user.get(user_id)
        if ids is not None:
            ids.discard(reminder_id)
            if not ids:
                del self._jobs_by_user[user_id]

    # -- bucle ---------------------------------------------------------

    async def _run(self) -> None:
        while not self._stopped:
            self._wake.clear()
            now = _utcnow()
            try:
                await self.process_due(now)
            except Exception:
                logger.exception("Scheduler: error al procesar vencidos")
            if self._stopped:
                break
            delay = self._seconds_until_next(now)
            timeout = (
                self._reload_interval
                if delay is None
                else min(delay, self._reload_interval)
            )
            timeout = max(timeout, 0.05)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout)
                timed_out = False
            except TimeoutError:
                timed_out = True
            if timed_out and not self._stopped:
                try:
                    await self.load_pending(_utcnow())
                except Exception:
                    logger.exception("Scheduler: error en la recarga periodica")

    def _seconds_until_next(self, now: datetime) -> float | None:
        job = self._queue.peek()
        if job is None:
            return None
        return max(0.0, (job.scheduled_at - now).total_seconds())

    # -- reclamacion y marca (transacciones cortas) --------------------

    async def _claim(self, job: HeapJob) -> MedicationReminder | None:
        async with self._session_factory() as session:
            claimed = await reminder_repository.claim_reminder(
                session, job.reminder_id, attempt_id=uuid4(), now=_utcnow()
            )
            await session.commit()
        return claimed

    async def _mark_sent(
        self, job: HeapJob, claimed: MedicationReminder
    ) -> MedicationReminder | None:
        assert claimed.current_attempt_id is not None
        async with self._session_factory() as session:
            marked = await reminder_repository.mark_sent(
                session,
                job.reminder_id,
                attempt_id=claimed.current_attempt_id,
            )
            await session.commit()
        return marked
