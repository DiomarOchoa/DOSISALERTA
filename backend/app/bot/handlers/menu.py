"""Menu principal y navegacion generica.

- ``show_main_menu``: vuelve al menu principal desde cualquier
  pantalla (boton "🏠 Menú principal", ``menu:main``).
- ``handle_text``: cualquier mensaje de texto que no sea un
  comando muestra el menu principal. Asi nadie necesita
  escribir comandos para usar el bot.
- ``unknown_callback``: ultimo recurso para un boton que ya no
  existe (por ejemplo, un mensaje viejo). Responde con el menu
  principal y un mensaje amable, sin errores tecnicos.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

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
    text, keyboard = render_main_menu()
    await query.edit_message_text(text, reply_markup=keyboard)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cualquier texto escrito muestra el menu principal."""
    if update.message is None:
        return
    text, keyboard = render_main_menu()
    await update.message.reply_text(text, reply_markup=keyboard)


async def unknown_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Boton desconocido: vuelve al menu principal sin asustar."""
    query = update.callback_query
    if query is None:
        return
    await query.answer("Esa opción ya no está disponible.")
    text, keyboard = render_main_menu()
    await query.edit_message_text(
        "Esa opción ya no está disponible.\n\n" + text, reply_markup=keyboard
    )
