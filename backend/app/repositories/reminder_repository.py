"""Consultas de recordatorios (Fase 4). Solo SQL, sin logica de negocio.

El repositorio solo consulta: el servicio decide (estados,
regeneracion). Los endpoints propios de recordatorios
(`GET /reminders/upcoming`, `GET /reminders/{id}`,
`POST /reminders/{id}/confirm`) llegan con su modulo (Fase 4);
aqui se necesitan la insercion masiva idempotente (UNIQUE
parcial sobre estados activos), la lectura de proximos por
tratamiento (seccion `upcoming_reminders` de D-1), la
cancelacion de futuros para los cambios de estado y el borrado
de PENDIENTE para la regeneracion. Las filas CANCELADA nunca
se borran (decision B).

La reclamacion atomica y el listado de pendientes llegan con
la Fase 5 (``claim_reminder``, ``mark_sent``, ``list_pending``):
el scheduler reclama un PENDIENTE y solo quien lo reclama puede
enviarlo y marcarlo ENVIADA (D18).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.logs import NotificationLog
from app.models.medications import TreatmentMedication
from app.models.reminders import MedicationReminder


def _with_relations(stmt):
    """Carga ansiosa de horario y vinculo -> medicamento.

    La respuesta `ReminderResponse` necesita la dosis (del
    vinculo) y el medicamento; sin esto, construirla tocaria
    relaciones perezosas fuera del contexto asincrono.
    """
    return stmt.options(
        selectinload(MedicationReminder.schedule),
        selectinload(MedicationReminder.treatment_medication).selectinload(
            TreatmentMedication.medication
        ),
    )


async def create_many(session: AsyncSession, rows: list[dict]) -> int:
    """Insercion masiva de recordatorios, idempotente.

    `INSERT ... ON CONFLICT DO NOTHING` sobre la UNIQUE parcial
    `(schedule_id, scheduled_at)` (`uq_reminders_schedule_time`,
    estados activos + TOMADA): regenerar nunca duplica un
    recordatorio activo ni una franja TOMADA, y un hueco con una
    fila CANCELADA (u otra inactiva) si admite un PENDIENTE nuevo.
    Devuelve el numero de filas insertadas (0 si `rows` esta vacio).
    """
    if not rows:
        return 0
    stmt = pg_insert(MedicationReminder).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["schedule_id", "scheduled_at"],
        index_where=MedicationReminder.status.in_(
            ["PENDIENTE", "ENVIANDO", "ENVIADA", "TOMADA"]
        ),
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def get_by_id(
    session: AsyncSession, reminder_id: int, user_id: int | None = None
) -> MedicationReminder | None:
    """Busca un recordatorio por id, con horario y vinculo.

    Con `user_id`, filtra por el dueno. Sin `user_id`, busca en
    cualquier cuenta: el servicio lo usa para distinguir 404 de
    403.
    """
    stmt = _with_relations(
        select(MedicationReminder).where(MedicationReminder.id == reminder_id)
    )
    if user_id is not None:
        stmt = stmt.where(MedicationReminder.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_upcoming(
    session: AsyncSession,
    user_id: int,
    from_dt: datetime,
    to_dt: datetime,
    limit: int = 100,
) -> list[MedicationReminder]:
    """Proximos recordatorios del usuario (PENDIENTE y ENVIADA),
    ordenados por `scheduled_at`.

    Es la consulta de `GET /reminders/upcoming` (su endpoint
    llega con el modulo de recordatorios); ENVIANDO no aparece
    porque es un estado transitorio de reclamacion por el motor
    (diseno §4.6.8).
    """
    stmt = _with_relations(
        select(MedicationReminder)
        .where(
            MedicationReminder.user_id == user_id,
            MedicationReminder.status.in_(["PENDIENTE", "ENVIADA"]),
            MedicationReminder.scheduled_at >= from_dt,
            MedicationReminder.scheduled_at <= to_dt,
        )
        .order_by(MedicationReminder.scheduled_at)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_upcoming_for_treatment(
    session: AsyncSession,
    treatment_id: int,
    user_id: int,
    from_dt: datetime,
    to_dt: datetime,
    limit: int = 100,
) -> list[MedicationReminder]:
    """Proximos recordatorios de un tratamiento (PENDIENTE y
    ENVIADA), ordenados por `scheduled_at`.

    Es la consulta de la seccion `upcoming_reminders` del detalle
    y del listado de tratamientos (D-1): solo se ejecuta cuando
    el actor tiene `perm_view_upcoming` (o es el paciente).
    """
    stmt = _with_relations(
        select(MedicationReminder)
        .join(
            TreatmentMedication,
            TreatmentMedication.id
            == MedicationReminder.treatment_medication_id,
        )
        .where(
            TreatmentMedication.treatment_id == treatment_id,
            MedicationReminder.user_id == user_id,
            MedicationReminder.status.in_(["PENDIENTE", "ENVIADA"]),
            MedicationReminder.scheduled_at >= from_dt,
            MedicationReminder.scheduled_at <= to_dt,
        )
        .order_by(MedicationReminder.scheduled_at)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def cancel_pending_for_schedule(
    session: AsyncSession, schedule_id: int, now: datetime
) -> int:
    """Cancela los recordatorios PENDIENTE y ENVIANDO futuros de
    un horario (status -> CANCELADA).

    Futuro = `scheduled_at >= now`. No toca TOMADA, POSPUESTA,
    PERDIDA, ENVIADA ni sus intakes: el historial se conserva
    (diseno §4.6.4).
    """
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.schedule_id == schedule_id,
            MedicationReminder.status.in_(["PENDIENTE", "ENVIANDO"]),
            MedicationReminder.scheduled_at >= now,
        )
        .values(status="CANCELADA")
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def cancel_pending_for_treatment(
    session: AsyncSession, treatment_id: int, now: datetime
) -> int:
    """Cancela los recordatorios PENDIENTE y ENVIANDO futuros de
    todo un tratamiento (status -> CANCELADA).

    Lo usan pausar, cancelar y completar (diseno §4.6.4).
    """
    subquery = select(TreatmentMedication.id).where(
        TreatmentMedication.treatment_id == treatment_id
    )
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.treatment_medication_id.in_(subquery),
            MedicationReminder.status.in_(["PENDIENTE", "ENVIANDO"]),
            MedicationReminder.scheduled_at >= now,
        )
        .values(status="CANCELADA")
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def cancel_pending_for_medication(
    session: AsyncSession, medication_id: int, user_id: int, now: datetime
) -> int:
    """Cancela los recordatorios PENDIENTE y ENVIANDO futuros de
    un medicamento (status -> CANCELADA).

    Lo usa desactivar un medicamento (Fase A, I-3, opcion A): al
    desactivar, sus recordatorios futuros se cancelan en la misma
    transaccion, para que el paciente deje de recibir avisos de un
    farmaco que ya no debe tomar. No toca TOMADA, POSPUESTA,
    PERDIDA ni ENVIADA: el historial se conserva (diseno §4.6.4).
    """
    subquery = select(TreatmentMedication.id).where(
        TreatmentMedication.medication_id == medication_id,
        TreatmentMedication.user_id == user_id,
    )
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.treatment_medication_id.in_(subquery),
            MedicationReminder.status.in_(["PENDIENTE", "ENVIANDO"]),
            MedicationReminder.scheduled_at >= now,
        )
        .values(status="CANCELADA")
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def list_cancelled_for_schedule(
    session: AsyncSession, schedule_id: int, now: datetime
) -> list[MedicationReminder]:
    """Filas CANCELADA futuras de un horario, ordenadas por
    fecha e id.

    Las usa el resume para relacionar cada recordatorio nuevo
    con la fila cancelada que reemplaza (`parent_reminder_id`);
    si hay varias CANCELADA en el mismo hueco (varios ciclos
    pausa+resume), el servicio toma la mas reciente (mayor id).
    """
    stmt = (
        select(MedicationReminder)
        .where(
            MedicationReminder.schedule_id == schedule_id,
            MedicationReminder.status == "CANCELADA",
            MedicationReminder.scheduled_at >= now,
        )
        .order_by(MedicationReminder.scheduled_at, MedicationReminder.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_pending_for_schedule(
    session: AsyncSession, schedule_id: int, now: datetime
) -> int:
    """Borrado fisico de los recordatorios PENDIENTE futuros de
    un horario.

    Solo PENDIENTE sin historial (sin intake ni logs): es el
    primer paso de la regeneracion (§4.7). Nunca borra TOMADA,
    POSPUESTA, PERDIDA, ENVIADA, ENVIANDO ni CANCELADA.
    """
    stmt = delete(MedicationReminder).where(
        MedicationReminder.schedule_id == schedule_id,
        MedicationReminder.status == "PENDIENTE",
        MedicationReminder.scheduled_at >= now,
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def claim_reminder(
    session: AsyncSession, reminder_id: int, *, attempt_id: UUID, now: datetime
) -> MedicationReminder | None:
    """Reclama un recordatorio PENDIENTE para enviarlo, de forma atomica (Fase 5, D18).

    Un solo UPDATE con WHERE de estado y RETURNING: PostgreSQL lo
    ejecuta como una operacion atomica, asi que de varias
    reclamaciones concurrentes del mismo recordatorio solo una
    puede ganar (las demas encuentran el estado ya en ENVIANDO y
    obtienen 0 filas). Quien reclama es el unico que puede enviar
    y marcar ENVIADA (con el mismo attempt_id). Devuelve la fila
    reclamada o None. Quien llama hace el commit.
    """
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.id == reminder_id,
            MedicationReminder.status == "PENDIENTE",
        )
        .values(
            status="ENVIANDO",
            current_attempt_id=attempt_id,
            claimed_at=now,
            attempt_count=MedicationReminder.attempt_count + 1,
        )
        .returning(MedicationReminder)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def mark_sent(
    session: AsyncSession, reminder_id: int, *, attempt_id: UUID
) -> MedicationReminder | None:
    """Marca ENVIADA un recordatorio reclamado, solo si el intento coincide.

    El WHERE exige estado ENVIANDO y el mismo ``current_attempt_id``
    de la reclamacion: solo el reclamante puede marcarlo. Devuelve
    la fila marcada o None. Quien llama hace el commit.
    """
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.id == reminder_id,
            MedicationReminder.status == "ENVIANDO",
            MedicationReminder.current_attempt_id == attempt_id,
        )
        .values(status="ENVIADA")
        .returning(MedicationReminder)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_pending(
    session: AsyncSession, *, from_dt: datetime, now: datetime, limit: int = 500
) -> list[MedicationReminder]:
    """Recordatorios PENDIENTE listos para (re)cargar, ordenados.

    Lo usa el scheduler para (re)cargar la cola (Fase 5, Etapas
    2-3). El orden es el mismo de la cola: scheduled_at y despues
    id. Se cargan los PENDIENTE con ``scheduled_at`` dentro de la
    ventana [from_dt, ...) y sin un ``next_attempt_at`` futuro, o
    con un ``next_attempt_at`` ya vencido (reintento pendiente).
    Un reintento no se recoge antes de su hora.
    """
    stmt = (
        select(MedicationReminder)
        .where(
            MedicationReminder.status == "PENDIENTE",
            or_(
                and_(
                    MedicationReminder.next_attempt_at.is_(None),
                    MedicationReminder.scheduled_at >= from_dt,
                ),
                and_(
                    MedicationReminder.next_attempt_at.is_not(None),
                    MedicationReminder.next_attempt_at <= now,
                ),
            ),
        )
        .order_by(MedicationReminder.scheduled_at, MedicationReminder.id)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_for_sending(
    session: AsyncSession, reminder_id: int
) -> MedicationReminder | None:
    """Recordatorio con horario, vinculo y medicamento (Fase 5, Etapa 3).

    Lo usa el scheduler para construir el texto del aviso. Sin
    estas relaciones, construirlo tocaria relaciones perezosas
    fuera del contexto asincrono.
    """
    stmt = (
        select(MedicationReminder)
        .where(MedicationReminder.id == reminder_id)
        .options(
            selectinload(MedicationReminder.schedule),
            selectinload(MedicationReminder.treatment_medication).selectinload(
                TreatmentMedication.medication
            ),
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def set_next_attempt(
    session: AsyncSession,
    reminder_id: int,
    *,
    attempt_id: UUID,
    next_attempt_at: datetime,
) -> MedicationReminder | None:
    """Vuelve un recordatorio reclamado a PENDIENTE con su proximo intento.

    Solo el reclamante puede hacerlo (el WHERE exige estado
    ENVIANDO y el mismo ``current_attempt_id``). Es el reintento
    de la Etapa 3: el cargador lo recogera cuando llegue
    ``next_attempt_at``. Devuelve la fila o None. Quien llama
    hace el commit.
    """
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.id == reminder_id,
            MedicationReminder.status == "ENVIANDO",
            MedicationReminder.current_attempt_id == attempt_id,
        )
        .values(status="PENDIENTE", next_attempt_at=next_attempt_at)
        .returning(MedicationReminder)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def mark_failed(
    session: AsyncSession, reminder_id: int, *, attempt_id: UUID
) -> MedicationReminder | None:
    """Marca FALLIDA un recordatorio reclamado, solo si el intento coincide.

    FALLIDA es terminal: no hay vuelta a un envio nuevo del mismo
    recordatorio (spec §3.4). Devuelve la fila o None. Quien
    llama hace el commit.
    """
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.id == reminder_id,
            MedicationReminder.status == "ENVIANDO",
            MedicationReminder.current_attempt_id == attempt_id,
        )
        .values(status="FALLIDA")
        .returning(MedicationReminder)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def transition_to_taken(
    session: AsyncSession,
    reminder_id: int,
    user_id: int,
    *,
    from_statuses: tuple[str, ...],
) -> MedicationReminder | None:
    """Pasa un recordatorio a TOMADA, de forma atomica (Fase 5, Etapa 4).

    Un solo UPDATE con WHERE de estado y RETURNING: si el estado
    ya no esta en `from_statuses` (otra operacion gano la
    carrera), devuelve None y no cambia nada. Solo el dueno
    (WHERE de user_id). Incrementa `version` (bloqueo optimista).
    Devuelve la fila tras el cambio o None. Quien llama hace el
    commit (junto a la creacion de la toma, en la misma
    transaccion).
    """
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.id == reminder_id,
            MedicationReminder.user_id == user_id,
            MedicationReminder.status.in_(from_statuses),
        )
        .values(status="TOMADA", version=MedicationReminder.version + 1)
        .returning(MedicationReminder)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def transition_to_postponed(
    session: AsyncSession,
    reminder_id: int,
    user_id: int,
    *,
    from_statuses: tuple[str, ...],
) -> MedicationReminder | None:
    """Pasa un recordatorio a POSPUESTA, de forma atomica (Fase 5, Etapa 4).

    Igual que `transition_to_taken`: un solo UPDATE con WHERE de
    estado y RETURNING; si el estado ya cambio, devuelve None y
    no cambia nada. Devuelve la fila tras el cambio o None. Quien
    llama hace el commit (junto a la creacion del hijo).
    """
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.id == reminder_id,
            MedicationReminder.user_id == user_id,
            MedicationReminder.status.in_(from_statuses),
        )
        .values(status="POSPUESTA", version=MedicationReminder.version + 1)
        .returning(MedicationReminder)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_child(
    session: AsyncSession,
    *,
    original: MedicationReminder,
    scheduled_at: datetime,
) -> MedicationReminder:
    """Crea el recordatorio hijo de una posposicion (Fase 5, Etapa 4).

    Hereda horario, vinculo y usuario del original; apunta a el
    con `parent_reminder_id` y sube `postponed_count` en uno. El
    indice unico parcial (`uq_reminders_schedule_time`) rechaza
    el INSERT si ya hay un recordatorio activo en ese instante
    para el horario: el servicio lo convierte en 409 con rollback
    completo. Quien llama hace el commit.
    """
    child = MedicationReminder(
        schedule_id=original.schedule_id,
        treatment_medication_id=original.treatment_medication_id,
        user_id=original.user_id,
        scheduled_at=scheduled_at,
        status="PENDIENTE",
        parent_reminder_id=original.id,
        postponed_count=original.postponed_count + 1,
    )
    session.add(child)
    return child


async def list_overdue(
    session: AsyncSession, *, cutoff: datetime, limit: int = 500
) -> list[MedicationReminder]:
    """Recordatorios vencidos fuera de gracia, para la reconciliación.

    Estados PENDIENTE, ENVIADA y ENVIANDO con ``scheduled_at``
    anterior al corte (ahora - 30 min), ordenados por
    ``scheduled_at`` e ``id``. Solo lectura; la marca es
    `mark_perdida`. (Fase 5, Etapa 5).
    """
    stmt = (
        select(MedicationReminder)
        .where(
            MedicationReminder.status.in_(["PENDIENTE", "ENVIADA", "ENVIANDO"]),
            MedicationReminder.scheduled_at < cutoff,
        )
        .order_by(MedicationReminder.scheduled_at, MedicationReminder.id)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def mark_perdida(
    session: AsyncSession, *, cutoff: datetime, limit: int = 500
) -> list[int]:
    """Marca PERDIDA los vencidos fuera de gracia, en un solo UPDATE atómico.

    Una subconsulta elige como máximo `limit` ids (los más
    vencidos, por ``scheduled_at`` e ``id``) y el UPDATE exterior
    vuelve a validar las condiciones: el límite se cumple dentro
    de la operación atómica (precisión B) y una fila que cambió
    de estado por una operación concurrente se salta (precisión
    C, PostgreSQL revalúa el WHERE al escribir). TOMADA,
    POSPUESTA, CANCELADA y FALLIDA no pueden coincidir con el
    ``IN``. No crea tomas. Devuelve las ids marcadas. Quien
    llama hace el commit. (Fase 5, Etapa 5).
    """
    subq = (
        select(MedicationReminder.id)
        .where(
            MedicationReminder.status.in_(["PENDIENTE", "ENVIADA", "ENVIANDO"]),
            MedicationReminder.scheduled_at < cutoff,
        )
        .order_by(MedicationReminder.scheduled_at, MedicationReminder.id)
        .limit(limit)
        .scalar_subquery()
    )
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.id.in_(subq),
            MedicationReminder.status.in_(["PENDIENTE", "ENVIADA", "ENVIANDO"]),
            MedicationReminder.scheduled_at < cutoff,
        )
        .values(status="PERDIDA", version=MedicationReminder.version + 1)
        .returning(MedicationReminder.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def release_stale_sending(
    session: AsyncSession,
    *,
    stale_cutoff: datetime,
    grace_cutoff: datetime,
    limit: int = 500,
) -> list[int]:
    """Libera ENVIANDO caídos (sin registro) devolviéndolos a PENDIENTE.

    ENVIANDO con ``claimed_at`` anterior a `stale_cutoff` (ahora
    - 5 min), sin log para su ``current_attempt_id`` y dentro de
    gracia (``scheduled_at`` posterior a `grace_cutoff`). No se
    exige ``next_attempt_at IS NULL``: una fila caída puede traer
    un valor viejo de un ciclo anterior (la reclamación no lo
    limpia) y ese valor no la descalifica; la liberación lo
    limpia. Limpia ``current_attempt_id``, ``claimed_at`` y
    ``next_attempt_at``; conserva ``attempt_count``. Igual que
    `mark_perdida`: subconsulta con LIMIT y re-validación de
    todas las condiciones en el UPDATE exterior (precisiones B
    y C). Devuelve las ids liberadas. Quien llama hace el commit.
    (Fase 5, Etapa 5).
    """
    no_log = ~exists().where(
        NotificationLog.attempt_id == MedicationReminder.current_attempt_id
    )
    subq = (
        select(MedicationReminder.id)
        .where(
            MedicationReminder.status == "ENVIANDO",
            MedicationReminder.claimed_at < stale_cutoff,
            MedicationReminder.scheduled_at >= grace_cutoff,
            no_log,
        )
        .order_by(MedicationReminder.claimed_at, MedicationReminder.id)
        .limit(limit)
        .scalar_subquery()
    )
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.id.in_(subq),
            MedicationReminder.status == "ENVIANDO",
            MedicationReminder.claimed_at < stale_cutoff,
            MedicationReminder.scheduled_at >= grace_cutoff,
            no_log,
        )
        .values(
            status="PENDIENTE",
            current_attempt_id=None,
            claimed_at=None,
            next_attempt_at=None,
            version=MedicationReminder.version + 1,
        )
        .returning(MedicationReminder.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
