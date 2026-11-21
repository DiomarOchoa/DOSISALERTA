"""Scheduler del motor de recordatorios (Fase 5, Etapas 2-3, D16/D18/D19).

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
  confirmarse); un vencido fuera de ella no se carga: el
  reconciliador lo marca PERDIDA (Etapa 5).

Envio real (Etapa 3):

- El chat se resuelve **antes** de reclamar: sin cuenta de
  Telegram vinculada no hay aviso (spec §3.1), asi que no se
  reclama, no se envia y no se registra nada.
- Cada intento queda en ``notification_logs`` y el cambio de
  estado del recordatorio se escribe **en la misma transaccion**:
  o quedan los dos, o ninguno.
- Un resultado simulado (solo en pruebas) no es una entrega
  real: no escribe log ni marca ENVIADA; el recordatorio queda
  ENVIANDO (reclamado).
- Reintentos (``retry_policy``): fallo claro +1 min y +5 min,
  ambiguo +10 min, 429 con el ``retry_after`` exacto de Telegram
  (sin tope); maximo 3 intentos y el recordatorio pasa a FALLIDA.

Reconciliación (Etapa 5):

- En cada recarga y al arrancar, el reconciliador marca PERDIDA
  los vencidos fuera de la gracia y libera los ENVIANDO caídos
  (reclamados hace más de 5 minutos sin registro) a PENDIENTE.
  Los reintentos no los libera: vuelven a PENDIENTE con
  ``next_attempt_at`` y el cargador los recoge cuando vence su
  hora.

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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms.reminder_heap import HeapJob, PriorityQueue, ReminderHeap
from app.models.medications import Treatment
from app.models.reminders import MedicationReminder
from app.models.users import User
from app.repositories import (
    notification_log_repository,
    reminder_repository,
    telegram_account_repository,
)
from app.scheduler.reconciliation import Reconciler
from app.scheduler.retry_policy import (
    AMBIGUOUS_DELAY,
    CLEAR_FAILURE_DELAYS,
    decide,
)
from app.scheduler.sender import SendPayload, Sender, SimulatedSender
from app.scheduler.telegram_sender import build_reminder_text

__all__ = ["ReminderScheduler"]

logger = logging.getLogger(__name__)

# Ventana de gracia del diseno: una dosis no confirmada en 30
# minutos es PERDIDA (Etapa 5). Hasta entonces, el aviso todavia
# tiene sentido y el scheduler lo envia.
GRACE_MINUTES = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _Prepared:
    """Recordatorio listo para enviar (chat resuelto, texto hecho)."""

    reminder: MedicationReminder
    chat_id: int
    payload: SendPayload


class ReminderScheduler:
    """Bucle del motor: cola en memoria + reclamacion atomica en BD."""

    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        sender: Sender,
        *,
        queue_factory: Callable[[], PriorityQueue] = ReminderHeap,
        reload_interval_seconds: float = 60.0,
        clear_delays: tuple[timedelta, ...] = CLEAR_FAILURE_DELAYS,
        ambiguous_delay: timedelta = AMBIGUOUS_DELAY,
    ) -> None:
        self._session_factory = session_factory
        self._sender = sender
        self._queue = queue_factory()
        self._jobs_by_id: dict[int, tuple[HeapJob, int]] = {}
        self._jobs_by_user: dict[int, set[int]] = {}
        self._reload_interval = reload_interval_seconds
        self._clear_delays = clear_delays
        self._ambiguous_delay = ambiguous_delay
        self._reconciler = Reconciler(
            session_factory,
            grace_minutes=GRACE_MINUTES,
            simulated=isinstance(sender, SimulatedSender),
        )
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
        await self._reconcile(_utcnow())
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

    async def _reconcile(self, now: datetime) -> None:
        """Una pasada de reconciliación + limpieza de la cola.

        Nunca levanta una excepción (el reconciliador ya registra
        cada regla por separado): un fallo aquí no detiene el
        bucle. Los PERDIDA se sacan de la cola en memoria; si no
        se hiciera, la reclamación seguiría protegiendo el envío.
        """
        try:
            result = await self._reconciler.reconcile(now)
        except Exception:
            logger.exception("Scheduler: error en la reconciliación")
            return
        for reminder_id in result.perdida_ids:
            self.remove_job(reminder_id)

    async def load_pending(self, now: datetime) -> int:
        """(Re)carga los PENDIENTE desde la BD y los encola.

        Solo los PENDIENTE con ``scheduled_at`` dentro de la
        ventana [ahora - gracia, ...) y sin un ``next_attempt_at``
        futuro (un reintento no se recoge antes de su hora), o con
        un ``next_attempt_at`` ya vencido (reintento pendiente):
        los ENVIADA, TOMADA, POSPUESTA, PERDIDA, CANCELADA y
        FALLIDA no vuelven a la cola, y los vencidos fuera de la
        gracia quedan en la BD para la Etapa 5. Re-encolar un id
        ya en cola lo reemplaza (semantica de ``push``), asi que
        recargar es seguro. Devuelve cuantos se cargaron.
        """
        from_dt = now - timedelta(minutes=GRACE_MINUTES)
        async with self._session_factory() as session:
            rows = await reminder_repository.list_pending(
                session, from_dt=from_dt, now=now
            )
        count = 0
        for row in rows:
            self.add_job(HeapJob(row.scheduled_at, row.id), row.user_id)
            count += 1
        return count

    async def process_due(self, now: datetime) -> list[int]:
        """Procesa los trabajos vencidos hasta ``now``.

        Por cada trabajo vencido: lo saca de la cola y de los
        indices, resuelve el chat (sin cuenta vinculada no hay
        aviso: se suelta sin reclamar, sin enviar y sin registrar
        nada), lo reclama en la BD y, solo si la reclamacion
        gana, lo envia. El intento y el cambio de estado se
        escriben en una sola transaccion. Un resultado simulado
        no marca ENVIADA ni escribe log (el recordatorio queda
        ENVIANDO). Devuelve los ids enviados de verdad.
        """
        sent: list[int] = []
        while True:
            job = self._queue.peek()
            if job is None or job.scheduled_at > now:
                return sent
            job = self._queue.pop()
            assert job is not None
            self._drop_from_indexes(job.reminder_id)
            prepared = await self._prepare(job)
            if prepared is None:
                continue
            claimed = await self._claim(job)
            if claimed is None:
                # Otro lo reclamo, o ya no esta PENDIENTE (cancelado,
                # por ejemplo): no se envia nada.
                continue
            result = await self._sender.send(prepared.payload)
            if result.simulated:
                # Modo simulado (solo en pruebas): no hubo entrega
                # real, asi que no se escribe log ni se marca
                # ENVIADA. El recordatorio queda ENVIANDO.
                continue
            await self._record_attempt(job, claimed, result)
            if result.ok and result.telegram_message_id is not None:
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
                await self._reconcile(_utcnow())
                try:
                    await self.load_pending(_utcnow())
                except Exception:
                    logger.exception("Scheduler: error en la recarga periodica")

    def _seconds_until_next(self, now: datetime) -> float | None:
        job = self._queue.peek()
        if job is None:
            return None
        return max(0.0, (job.scheduled_at - now).total_seconds())

    # -- preparacion, reclamacion y registro --------------------------

    async def _prepare(self, job: HeapJob) -> _Prepared | None:
        """Resuelve el chat y construye el texto del aviso.

        Devuelve None si el recordatorio ya no existe, si no hay
        usuario, o si no hay cuenta de Telegram vinculada (en ese
        caso no se reclama ni se envia nada: spec §3.1).
        """
        async with self._session_factory() as session:
            reminder = await reminder_repository.get_for_sending(
                session, job.reminder_id
            )
            if reminder is None:
                return None
            user = await session.get(User, reminder.user_id)
            if user is None:
                return None
            chat_id = await telegram_account_repository.get_linked_chat_id(
                session, reminder.user_id
            )
            if chat_id is None:
                return None
            link = reminder.treatment_medication
            medication = link.medication
            treatment = await session.get(Treatment, link.treatment_id)
            title = treatment.title if treatment is not None else ""
        text = build_reminder_text(
            medication_name=medication.name,
            dose_amount=link.dose_amount,
            dose_unit=link.dose_unit,
            concentration=medication.concentration,
            treatment_title=title,
            scheduled_at=reminder.scheduled_at,
            user_timezone=user.timezone,
        )
        return _Prepared(
            reminder=reminder,
            chat_id=chat_id,
            payload=SendPayload(
                reminder_id=job.reminder_id,
                user_id=reminder.user_id,
                chat_id=chat_id,
                text=text,
                scheduled_at=job.scheduled_at,
            ),
        )

    async def _claim(self, job: HeapJob) -> MedicationReminder | None:
        async with self._session_factory() as session:
            claimed = await reminder_repository.claim_reminder(
                session, job.reminder_id, attempt_id=uuid4(), now=_utcnow()
            )
            await session.commit()
        return claimed

    async def _record_attempt(self, job: HeapJob, claimed, result) -> None:
        """Escribe el intento y el cambio de estado en una transaccion.

        El log y el estado van juntos: o quedan los dos, o ninguno.
        Solo el reclamante puede cambiar el estado (la marca exige
        su ``current_attempt_id``); si la marca no afecta a ninguna
        fila, se registra un aviso y el log ya quedo escrito.
        """
        at = _utcnow()
        decision = decide(
            result,
            attempt_count=claimed.attempt_count,
            now=at,
            clear_delays=self._clear_delays,
            ambiguous_delay=self._ambiguous_delay,
        )
        assert claimed.current_attempt_id is not None
        log_status = (
            "ENVIADA"
            if decision.action == "sent"
            else ("AMBIGUA" if result.kind == "ambiguous" else "FALLIDA")
        )
        async with self._session_factory() as session:
            await notification_log_repository.create_log(
                session,
                reminder_id=job.reminder_id,
                user_id=claimed.user_id,
                attempt_id=claimed.current_attempt_id,
                status=log_status,
                telegram_message_id=(
                    result.telegram_message_id
                    if decision.action == "sent"
                    else None
                ),
                sent_at=at if decision.action == "sent" else None,
                error=None if decision.action == "sent" else result.error,
            )
            if decision.action == "sent":
                marked = await reminder_repository.mark_sent(
                    session,
                    job.reminder_id,
                    attempt_id=claimed.current_attempt_id,
                )
            elif decision.action == "retry":
                assert decision.next_attempt_at is not None
                marked = await reminder_repository.set_next_attempt(
                    session,
                    job.reminder_id,
                    attempt_id=claimed.current_attempt_id,
                    next_attempt_at=decision.next_attempt_at,
                )
            else:  # "failed"
                marked = await reminder_repository.mark_failed(
                    session,
                    job.reminder_id,
                    attempt_id=claimed.current_attempt_id,
                )
            await session.commit()
        if marked is None:
            logger.warning(
                "Scheduler: el recordatorio %s no cambio de estado tras el intento",
                job.reminder_id,
            )
