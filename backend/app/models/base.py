"""Base declarativa de SQLAlchemy para DosisAlerta (Fase 2).

Todas las tablas del modelo (`docs/database/MODELO_DATOS.md` y
`docs/database/RELACIONES_CUIDADORES.md`) heredan de esta base, de
modo que Alembic las descubre a traves de ``Base.metadata``.

La convencion de nombres hace que las restricciones generadas por
Alembic tengan nombres deterministas y reproducibles en la
migracion inicial y en las siguientes.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarativa con convencion de nombres para restricciones."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
