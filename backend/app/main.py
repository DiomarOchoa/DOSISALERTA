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

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, health, medications, reminders, stats, treatments
from app.bot.config import BotConfig
from app.core.config import get_settings
from app.database import AsyncSessionLocal
from app.scheduler import ReminderScheduler, Sender, TelegramSender

logger = logging.getLogger(__name__)


def _sender_from_config() -> Sender | None:
    """El sender real si hay token de Telegram, o None.

    Sin token no hay envio: el scheduler no arranca (el sender
    simulado solo existe en las pruebas, nunca en el lifespan).
    """
    if not BotConfig.from_env().can_poll:
        return None
    return TelegramSender.from_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque y apagado: el scheduler del motor (Fase 5, Etapa 3).

    El scheduler corre solo si ``run_scheduler`` es True (o si
    ``settings.scheduler_enabled`` lo enciende). El sender es el
    inyectado en ``create_app`` o, si no hay ninguno, el real
    desde ``BotConfig``; sin token, el scheduler no arranca y la
    API sigue sirviendo HTTP (queda registrado un aviso).
    """
    scheduler = None
    if app.state.run_scheduler:
        sender = app.state.sender or _sender_from_config()
        if sender is None:
            logger.warning(
                "Scheduler desactivado: no hay token de Telegram "
                "configurado. La API sigue sirviendo HTTP."
            )
            app.state.scheduler = None
        else:
            scheduler = ReminderScheduler(
                app.state.session_factory, sender
            )
            app.state.scheduler = scheduler
            await scheduler.start()
    else:
        app.state.scheduler = None
    yield
    if scheduler is not None:
        await scheduler.stop()
        app.state.scheduler = None


def create_app(
    *,
    run_scheduler: bool | None = None,
    session_factory=None,
    sender: Sender | None = None,
) -> FastAPI:
    """Crea y configura la aplicacion FastAPI.

    ``run_scheduler`` enciende el scheduler del motor en el
    lifespan. Si es None, sigue ``settings.scheduler_enabled``
    (False por defecto). ``session_factory`` es la fabrica de
    sesiones del scheduler; por defecto, la de la aplicacion
    (``AsyncSessionLocal``). ``sender`` es el sender del
    scheduler; si es None, el lifespan construye el real desde
    ``BotConfig`` (o no arranca el scheduler si no hay token).
    Las pruebas pasan su propia fabrica y su propio sender.
    """
    settings = get_settings()
    if run_scheduler is None:
        run_scheduler = settings.scheduler_enabled

    app = FastAPI(
        title=settings.app_name,
        description=(
            "API de DosisAlerta: gestion y seguimiento de tratamientos "
            "medicos. Expone el endpoint de salud y, desde la Fase 3, "
            "la autenticacion JWT (`/api/v1/auth`); desde la Fase 4, "
            "el catalogo de medicamentos (`/api/v1/medications`) y "
            "los tratamientos con sus vinculos "
            "(`/api/v1/treatments`); la "
            "documentacion completa se genera sola en /docs."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.run_scheduler = run_scheduler
    app.state.session_factory = session_factory or AsyncSessionLocal
    app.state.sender = sender

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
    # reglas de cuidador (diseno 4.6.2). Los routers de
    # horarios y recordatorios llegan con sus modulos.
    app.include_router(medications.router, prefix="/api/v1")

    # Tratamientos y vinculos (Fase 4, RF05/RF06/RF08): planes con
    # medicamentos, dosis y horarios, con maquina de estados y
    # generacion de recordatorios (diseno 4.6.3-4.6.5 y 4.7).
    app.include_router(treatments.router, prefix="/api/v1")

    # Tomas (Fase 5, Etapa 4, RF11/RF12): confirmar y posponer
    # recordatorios. Solo paciente; el servicio decide el 403.
    app.include_router(reminders.router, prefix="/api/v1")

    # Estadísticas de cumplimiento (Fase 7, RF14): porcentaje de
    # tomas a tiempo por periodo, con desglose por motivo de
    # cancelación (D-11). El historial vive en el router de
    # recordatorios (D-5).
    app.include_router(stats.router, prefix="/api/v1")

    return app


# Instancia que usa uvicorn: ``uvicorn app.main:app``.
app = create_app()
