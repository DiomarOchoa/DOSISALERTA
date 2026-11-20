"""Consultas de vinculos tratamiento x medicamento (Fase 4).

Solo SQL, sin logica de negocio. El servicio decide (404/403/
409, solo paciente). `create`, `update` y `deactivate` solo
anaden o modifican objetos en la sesion; el commit lo hace el
servicio, en una sola transaccion (patron de Fase 3).

La dosis vive en el vinculo, no en el catalogo ni en el plan
(MODELO_DATOS §3.4): aqui se edita y aqui se lee.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.medications import TreatmentMedication


def _with_relations(stmt):
    """Carga ansiosa de medicamento y horarios del vinculo."""
    return stmt.options(
        selectinload(TreatmentMedication.medication),
        selectinload(TreatmentMedication.schedules),
    )


def create(
    session: AsyncSession,
    *,
    user_id: int,
    treatment_id: int,
    medication_id: int,
    dose_amount: Decimal,
    dose_unit: str,
    instructions: str | None = None,
) -> TreatmentMedication:
    """Crea el objeto TreatmentMedication y lo anade a la sesion
    (sin commit).

    El servicio valida antes existencia, propiedad, que el
    medicamento este activo y que no haya un vinculo activo
    duplicado; la garantia ultima es el indice parcial
    `uq_treatment_meds_active`.
    """
    link = TreatmentMedication(
        user_id=user_id,
        treatment_id=treatment_id,
        medication_id=medication_id,
        dose_amount=dose_amount,
        dose_unit=dose_unit,
        instructions=instructions,
        is_active=True,
    )
    session.add(link)
    return link


async def get_by_id(
    session: AsyncSession,
    link_id: int,
    user_id: int | None = None,
    treatment_id: int | None = None,
) -> TreatmentMedication | None:
    """Busca un vinculo por id, con medicamento y horarios.

    Con `user_id` y/o `treatment_id`, filtra por el dueno y por
    el tratamiento (el caso normal). Sin ellos, busca en
    cualquier cuenta y tratamiento: el servicio lo usa para
    distinguir 404 (no existe en este tratamiento) de 403
    (existe, pero es de otro usuario).
    """
    stmt = _with_relations(
        select(TreatmentMedication).where(TreatmentMedication.id == link_id)
    )
    if user_id is not None:
        stmt = stmt.where(TreatmentMedication.user_id == user_id)
    if treatment_id is not None:
        stmt = stmt.where(TreatmentMedication.treatment_id == treatment_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_active_by_treatment_and_medication(
    session: AsyncSession,
    treatment_id: int,
    medication_id: int,
    user_id: int,
) -> TreatmentMedication | None:
    """Vinculo ACTIVO de un medicamento en un tratamiento, si hay.

    Pre-chequeo rapido del 409 (la garantia es el indice parcial
    `uq_treatment_meds_active`). Un vinculo desactivado no
    cuenta: el medicamento se puede volver a anadir despues.
    """
    stmt = select(TreatmentMedication).where(
        TreatmentMedication.treatment_id == treatment_id,
        TreatmentMedication.medication_id == medication_id,
        TreatmentMedication.user_id == user_id,
        TreatmentMedication.is_active.is_(True),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_by_treatment(
    session: AsyncSession, treatment_id: int, user_id: int
) -> list[TreatmentMedication]:
    """Vinculos de un tratamiento, con medicamento y horarios."""
    stmt = _with_relations(
        select(TreatmentMedication)
        .where(
            TreatmentMedication.treatment_id == treatment_id,
            TreatmentMedication.user_id == user_id,
        )
        .order_by(TreatmentMedication.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def update(
    session: AsyncSession, link: TreatmentMedication, **fields
) -> TreatmentMedication:
    """Aplica los campos dados al vinculo (sin commit).

    Solo se pasan los campos presentes en el payload
    (`model_dump(exclude_unset=True)` en el servicio): dosis,
    unidad o instrucciones. No esta en la lista del diseno
    §4.5, pero el endpoint `PATCH .../medications/{link_id}`
    (diseno §4.3) lo exige: sin el no hay como cambiar la dosis.
    """
    for name, value in fields.items():
        setattr(link, name, value)
    return link


def deactivate(
    session: AsyncSession, link: TreatmentMedication
) -> TreatmentMedication:
    """Desactivacion logica (`is_active=False`, sin commit).

    No borra nada: el historial (tomas confirmadas) se conserva
    y el indice parcial permite volver a anadir el mismo
    medicamento despues (diseno §4.6.5).
    """
    link.is_active = False
    return link
