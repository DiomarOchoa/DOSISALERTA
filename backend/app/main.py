"""Punto de entrada del backend de DosisAlerta.

Se ejecuta con::

    uvicorn app.main:app --reload --port 8000

desde la carpeta ``backend/`` (con el entorno virtual activado y el
paquete instalado con ``pip install -r requirements-lock.txt`` y
``pip install -e . --no-deps``).

La aplicacion se construye con una funcion factoria (``create_app``)
para que las pruebas puedan crear una aplicacion nueva sin depender
de un objeto global: eso hace que ``test_health.py`` sea rapido y
aislado, sin levantar un servidor real.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, health, medications
from app.core.config import get_settings


def create_app() -> FastAPI:
    """Crea y configura la aplicacion FastAPI."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "API de DosisAlerta: gestion y seguimiento de tratamientos "
            "medicos. Expone el endpoint de salud y, desde la Fase 3, "
            "la autenticacion JWT (`/api/v1/auth`); desde la Fase 4, "
            "el catalogo de medicamentos (`/api/v1/medications`); la "
            "documentacion completa se genera sola en /docs."
        ),
        version="0.1.0",
    )

    # CORS: solo el frontend local en desarrollo. En produccion, la
    # lista vendra de la variable CORS_ORIGINS, nunca de "*".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Salud: ruta canonica y ruta versionada, misma respuesta.
    app.include_router(health.router)
    app.include_router(health.router, prefix="/api/v1")

    # Autenticacion JWT (Fase 3): registro, login, refresh, logout y /me.
    # Sin manejador generico de excepciones: FastAPI gestiona
    # HTTPException (401/409) y RequestValidationError (422) con sus
    # manejadores propios; un catch-all los convertiria en 500.
    app.include_router(auth.router, prefix="/api/v1")

    # Medicamentos (Fase 4, RF04): catalogo propio del usuario, con
    # reglas de cuidador (diseno §4.6.2). Los routers de
    # tratamientos, horarios y recordatorios llegan con sus modulos.
    app.include_router(medications.router, prefix="/api/v1")

    return app


# Instancia que usa uvicorn: ``uvicorn app.main:app``.
app = create_app()
