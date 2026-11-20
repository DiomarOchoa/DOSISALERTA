"""Consultas de tratamientos (Fase 4). Solo SQL, sin logica de negocio.

El repositorio solo consulta: el servicio decide (404/403/409,
reglas del cuidador, maquina de estados). `create`, `update` y
`update_status` solo anaden o modifican objetos en la sesion;
el commit lo hace el servicio, en una sola transaccion (patron
de Fase 3).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.medications import Treatment, TreatmentMedication


def _with_relations(stmt):
    """Carga ansiosa de vinculos -> medicamento y horarios.

    Sin ella, construir la respuesta tocaria relaciones perezosas
    fuera del contexto asincrono (MissingGreenlet).
    """
    return stmt.options(
        selectinload(Treatment.treatment_medications).selectinload(
            TreatmentMedication.medication
        ),
        selectinload(Treatment.treatment_medications).selectinload(
            TreatmentMedication.schedules
        ),
    )


def create(
    session: AsyncSession,
    *,
    user_id: int,
    title: str,
    notes: str | None = None,
    start_date: date,
    end_date: date | None = None,
) -> Treatment:
    """Crea el objeto Treatment y lo anade a la sesion (sin commit).

    Nace en estado ACTIVO; el servicio valida antes que
    `end_date >= start_date` (400), sin dejar que el CHECK de
    BD lo convierta en 500.
    """
    treatment = Treatment(
        user_id=user_id,
        title=title,
        notes=notes,
        start_date=start_date,
        end_date=end_date,
        status="ACTIVO",
    )
    session.add(treatment)
    return treatment


async def get_by_id(
    session: AsyncSession, treatment_id: int, user_id: int | None = None
) -> Treatment | None:
    """Busca un tratamiento por id, con vinculos, medicamentos y
    horarios cargados.

    Con `user_id`, filtra por el dueno (el caso normal: el
    servicio ya resolvio el usuario efectivo). Sin `user_id`,
    busca en cualquier cuenta: el servicio lo usa para distinguir
    404 (no existe) de 403 (existe, pero es de otro usuario).
    """
    stmt = _with_relations(
        select(Treatment).where(Treatment.id == treatment_id)
    )
    if user_id is not None:
        stmt = stmt.where(Treatment.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_by_user(
    session: AsyncSession,
    user_id: int,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[Treatment]:
    """Tratamientos de un usuario, del mas reciente al mas antiguo.

    Con `status`, solo los de ese estado. El listado nunca mezcla
    cuentas: el filtro por `user_id` es obligatorio (diseno
    §4.10, R4). Cada elemento trae vinculos, medicamentos y
    horarios cargados (el servicio filtra las secciones por D-1).
    """
    stmt = _with_relations(
        select(Treatment)
        .where(Treatment.user_id == user_id)
        .order_by(Treatment.start_date.desc(), Treatment.id.desc())
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(Treatment.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def update(session: AsyncSession, treatment: Treatment, **fields) -> Treatment:
    """Aplica los campos dados al objeto (sin commit).

    Solo se pasan los campos presentes en el payload
    (`model_dump(exclude_unset=True)` en el servicio): un campo
    ausente no se toca y un campo en `None` lo borra (p. ej.
    quitar `end_date`).
    """
    for name, value in fields.items():
        setattr(treatment, name, value)
    return treatment


def update_status(
    session: AsyncSession, treatment: Treatment, status: str
) -> Treatment:
    """Cambia el estado del tratamiento (sin commit).

    La maquina de estados la impone el servicio (diseno §4.6.4),
    no este repositorio ni el CHECK de BD.
    """
    treatment.status = status
    return treatment
