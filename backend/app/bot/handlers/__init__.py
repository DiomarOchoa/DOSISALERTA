"""Handlers del bot: un modulo por seccion del menu.

El orden importa: los handlers especificos van antes que el
generico de texto y que el de callbacks desconocidos, porque
python-telegram-bot prueba los handlers en el orden en que se
registran dentro de cada grupo.
"""

from __future__ import annotations

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.bot.handlers import (
    caregivers,
    help as help_handler,
    history,
    medications,
    menu,
    reminders,
    settings,
    start,
    treatments,
)


def register_handlers(application: Application) -> None:
    """Registra todos los handlers del bot en la aplicacion."""
    application.add_handler(CommandHandler("start", start.start))
    application.add_handler(CommandHandler("help", help_handler.show_help_command))
    application.add_handler(CallbackQueryHandler(menu.show_main_menu, pattern=r"^menu:main$"))
    application.add_handler(
        CallbackQueryHandler(medications.show_medications, pattern=r"^menu:medications$")
    )
    application.add_handler(
        CallbackQueryHandler(medications.show_medication_detail, pattern=r"^med:")
    )
    application.add_handler(
        CallbackQueryHandler(reminders.show_upcoming, pattern=r"^menu:reminders$")
    )
    application.add_handler(
        CallbackQueryHandler(treatments.show_treatments, pattern=r"^menu:treatments$")
    )
    application.add_handler(
        CallbackQueryHandler(treatments.show_treatment_detail, pattern=r"^treat:")
    )
    application.add_handler(CallbackQueryHandler(history.show_history, pattern=r"^menu:history$"))
    application.add_handler(
        CallbackQueryHandler(caregivers.show_caregivers, pattern=r"^menu:caregivers$")
    )
    application.add_handler(
        CallbackQueryHandler(settings.show_settings, pattern=r"^menu:settings$")
    )
    application.add_handler(CallbackQueryHandler(help_handler.show_help, pattern=r"^menu:help$"))
    # Texto libre (sin comando): muestra el menu principal.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu.handle_text))
    # Ultimo recurso: un boton que ya no existe no rompe el bot.
    application.add_handler(CallbackQueryHandler(menu.unknown_callback))
