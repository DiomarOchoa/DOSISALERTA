"""Comando /start: bienvenida y menu principal (Fase 6).

Si el chat no esta vinculado, el usuario recibe las instrucciones
de vinculacion (RF15/RF19). Si esta vinculado, la bienvenida con
su nombre y el menu principal.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.context import linked_session
from app.bot.keyboards import build_main_menu


def render_welcome(user_name: str | None) -> tuple[str, object]:
    """Texto de bienvenida y teclado del menu principal."""
    greeting = f"¡Hola, {user_name}!" if user_name else "¡Hola!"
    text = (
        f"{greeting} Soy DosisAlerta, tu ayudante de medicamentos.\n\n"
        "👇 Elige una opción:"
    )
    return text, build_main_menu()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde a /start con la bienvenida y el menu principal."""
    if update.message is None:
        return
    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        text, keyboard = render_welcome(user.name)
        await update.message.reply_text(text, reply_markup=keyboard)
