"""Handlers del bot: un modulo por seccion del menu (Fase 6).

El orden importa: los handlers especificos van antes que el
generico de texto y que el de callbacks desconocidos, porque
python-telegram-bot prueba los handlers en el orden en que se
registran dentro de cada grupo. Dentro de una familia de
callbacks (`med:`, `treat:`, `cg:`), las acciones especificas
van antes que el detalle generico.

Todos los handlers resuelven el usuario desde el chat_id
(RF19): un chat sin vincular recibe las instrucciones de
vinculacion y no ve ningun dato.
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
    intake,
    link,
    medications,
    menu,
    reminders,
    settings,
    start,
    treatments,
)


def register_handlers(application: Application) -> None:
    """Registra todos los handlers del bot en la aplicacion."""
    # Comandos.
    application.add_handler(CommandHandler("start", start.start))
    application.add_handler(CommandHandler("help", help_handler.show_help_command))
    application.add_handler(CommandHandler("vincular", link.handle_vincular))
    application.add_handler(
        CommandHandler("vincular_cuidador", link.handle_vincular_cuidador)
    )
    application.add_handler(
        CommandHandler("medicamentos", medications.show_medications)
    )
    application.add_handler(CommandHandler("proximas", reminders.show_upcoming))
    application.add_handler(CommandHandler("historial", history.show_history))
    # Menu principal.
    application.add_handler(CallbackQueryHandler(menu.show_main_menu, pattern=r"^menu:main$"))
    # Medicamentos: acciones especificas antes que el detalle.
    application.add_handler(
        CallbackQueryHandler(medications.show_medications, pattern=r"^menu:medications$")
    )
    application.add_handler(
        CallbackQueryHandler(medications.start_create, pattern=r"^med:create$")
    )
    application.add_handler(
        CallbackQueryHandler(medications.confirm_create, pattern=r"^med:create_confirm$")
    )
    application.add_handler(
        CallbackQueryHandler(medications.cancel_create, pattern=r"^med:create_cancel$")
    )
    application.add_handler(
        CallbackQueryHandler(medications.confirm_deactivate, pattern=r"^med:deactivate_confirm:")
    )
    application.add_handler(
        CallbackQueryHandler(medications.ask_deactivate, pattern=r"^med:deactivate:")
    )
    application.add_handler(
        CallbackQueryHandler(medications.show_medication_detail, pattern=r"^med:")
    )
    # Proximas tomas + confirmacion/posposicion de tomas.
    application.add_handler(
        CallbackQueryHandler(reminders.show_upcoming, pattern=r"^menu:reminders$")
    )
    application.add_handler(
        CallbackQueryHandler(intake.confirm_intake, pattern=r"^intake:confirm:")
    )
    application.add_handler(
        CallbackQueryHandler(intake.ask_postpone, pattern=r"^intake:postpone:")
    )
    application.add_handler(
        CallbackQueryHandler(intake.postpone_intake, pattern=r"^intake:delay:")
    )
    # Tratamientos: acciones especificas antes que el detalle.
    application.add_handler(
        CallbackQueryHandler(treatments.show_treatments, pattern=r"^menu:treatments$")
    )
    application.add_handler(
        CallbackQueryHandler(
            treatments.confirm_status_change, pattern=r"^treat:(pause|resume|cancel|complete)_confirm:"
        )
    )
    application.add_handler(
        CallbackQueryHandler(treatments.confirm_status_change, pattern=r"^treat:resume:")
    )
    application.add_handler(
        CallbackQueryHandler(
            treatments.ask_status_change, pattern=r"^treat:(pause|cancel|complete):"
        )
    )
    application.add_handler(
        CallbackQueryHandler(treatments.show_treatment_detail, pattern=r"^treat:")
    )
    # Historial.
    application.add_handler(CallbackQueryHandler(history.show_history, pattern=r"^menu:history$"))
    # Cuidadores.
    application.add_handler(
        CallbackQueryHandler(caregivers.show_caregivers, pattern=r"^menu:caregivers$")
    )
    application.add_handler(
        CallbackQueryHandler(caregivers.invite_caregiver, pattern=r"^cg:invite$")
    )
    application.add_handler(
        CallbackQueryHandler(caregivers.toggle_permission, pattern=r"^cg:toggle:")
    )
    application.add_handler(
        CallbackQueryHandler(caregivers.confirm_accept, pattern=r"^cg:accept_confirm:")
    )
    application.add_handler(
        CallbackQueryHandler(caregivers.show_permission_picker, pattern=r"^cg:accept:")
    )
    application.add_handler(
        CallbackQueryHandler(caregivers.confirm_revoke, pattern=r"^cg:revoke_confirm:")
    )
    application.add_handler(
        CallbackQueryHandler(caregivers.ask_revoke, pattern=r"^cg:revoke:")
    )
    # Configuracion.
    application.add_handler(
        CallbackQueryHandler(settings.show_settings, pattern=r"^menu:settings$")
    )
    application.add_handler(
        CallbackQueryHandler(settings.set_timezone, pattern=r"^tz:set:")
    )
    # Ayuda.
    application.add_handler(CallbackQueryHandler(help_handler.show_help, pattern=r"^menu:help$"))
    # Texto libre (sin comando): flujo de creacion o menu principal.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu.handle_text))
    # Ultimo recurso: un boton que ya no existe no rompe el bot.
    application.add_handler(CallbackQueryHandler(menu.unknown_callback))
