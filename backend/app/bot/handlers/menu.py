"""Menu principal y navegacion generica (Fase 6).

- ``show_main_menu``: vuelve al menu principal desde cualquier
  pantalla (boton "🏠 Menú principal", ``menu:main``). Solo para
  chats vinculados (RF19).
- ``handle_text``: cualquier mensaje de texto que no sea un
  comando. Si hay un flujo de creacion de medicamento activo, el
  texto pertenece a ese flujo; si no, muestra el menu principal
  (o el mensaje de vinculacion si el chat no esta vinculado).
- ``unknown_callback``: ultimo recurso para un boton que ya no
  existe (por ejemplo, un mensaje viejo). Responde con el menu
  principal y un mensaje amable, sin errores tecnicos.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.context import linked_session
from app.bot.keyboards import build_main_menu


def render_main_menu() -> tuple[str, object]:
    """Texto y teclado del menu principal."""
    text = "🏠 Menú principal\n\n👇 Elige una opción:"
    return text, build_main_menu()


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el menu principal al pulsar "🏠 Menú principal"."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        text, keyboard = render_main_menu()
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cualquier texto escrito: flujo activo o menu principal."""
    if update.message is None:
        return
    if context.user_data.get("med_create"):
        from app.bot.handlers import medications

        if await medications.handle_create_text(update, context):
            return
    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        text, keyboard = render_main_menu()
        await update.message.reply_text(text, reply_markup=keyboard)


async def unknown_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Boton desconocido: vuelve al menu principal sin asustar."""
    query = update.callback_query
    if query is None:
        return
    await query.answer("Esa opción ya no está disponible.")
    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        text, keyboard = render_main_menu()
        await query.edit_message_text(
            "Esa opción ya no está disponible.\n\n" + text, reply_markup=keyboard
        )
