"""Punto de entrada del proceso bot de DosisAlerta.

Se ejecuta con::

    python -m app.bot.main

desde la carpeta ``backend/`` (con el entorno virtual activado).

El bot corre como proceso independiente en polling (sin webhook
en desarrollo: no exige dominio ni HTTPS). Nunca accede directo
a PostgreSQL: en la Fase 6 llamara a los mismos servicios que
la web. En este esqueleto de demostracion los handlers usan
datos ficticios (``app.bot.services.mock_data``).

Sin ``TELEGRAM_BOT_TOKEN`` en ``.env`` el proceso no arranca:
falla con un mensaje claro, sin mostrar nunca el valor del
token.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes

from app.bot.config import BotConfig
from app.bot.handlers import register_handlers

logger = logging.getLogger(__name__)


async def on_error(update: Update | None, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra un error de handler sin tumbar el polling.

    Solo se registra el tipo de error, nunca el token ni datos
    de salud (RNF08). El usuario recibe un mensaje amable desde
    el handler que fallo, o nada si el fallo fue antes de
    responder.
    """
    logger.exception("Error en un handler del bot (%s)", type(context.error).__name__)


def build_application(config: BotConfig) -> Application:
    """Construye la aplicacion de Telegram sin conectar todavia.

    No hace polling ni llamadas de red: solo crea la aplicacion
    y registra los handlers. Por eso se puede probar sin token
    real y sin conexion a Telegram.
    """
    application = ApplicationBuilder().token(config.token).build()
    register_handlers(application)
    application.add_error_handler(on_error)
    return application


def main() -> None:
    """Lee la configuracion y arranca el polling."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    config = BotConfig.from_env()
    try:
        config.require_token()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
    logger.info("Iniciando el bot de DosisAlerta (@%s)...", config.username)
    application = build_application(config)
    application.run_polling()


if __name__ == "__main__":
    main()
