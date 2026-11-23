"""Seccion "Configuracion" (Fase 6, RF03).

Muestra la zona horaria actual del usuario y permite cambiarla
con el mismo servicio que la web: al cambiarla, las proximas
tomas pendientes se recalculan con la zona nueva (RNF04); las
tomas ya confirmadas o perdidas no cambian.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from app.bot.context import linked_session
from app.bot.keyboards import with_home

_ZONES = (
    "America/Bogota",
    "America/Lima",
    "America/Mexico_City",
    "America/Buenos_Aires",
    "America/Santiago",
    "America/New_York",
    "Europe/Madrid",
)


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Configuracion real (boton del menu)."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        lines = ["⚙️ Configuración", "", f"Zona horaria: {user.timezone}", ""]
        lines.append("Toca una zona para cambiarla:")
        rows: list[list[InlineKeyboardButton]] = []
        for zone in _ZONES:
            mark = "✅ " if zone == user.timezone else ""
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{mark}{zone}", callback_data=f"tz:set:{zone}"
                    )
                ]
            )
        lines.append("")
        lines.append(
            "Las tomas ya confirmadas o perdidas no cambian; "
            "solo se recalculan las pendientes futuras."
        )
        text = "\n".join(lines)
        keyboard = with_home(rows)
        if query is not None:
            await query.edit_message_text(text, reply_markup=keyboard)
        elif update.message is not None:
            await update.message.reply_text(text, reply_markup=keyboard)


async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cambia la zona horaria (boton de zona)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    zone = data.removeprefix("tz:set:")
    if zone not in _ZONES:
        await query.edit_message_text("Esa zona horaria no es válida.")
        return
    from app.schemas.auth import UserUpdate
    from app.services import auth_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        if zone == user.timezone:
            await query.edit_message_text(
                f"Tu zona horaria ya es {zone}.",
                reply_markup=with_home(
                    [
                        [
                            InlineKeyboardButton(
                                "⬅️ Configuración",
                                callback_data="menu:settings",
                            )
                        ]
                    ]
                ),
            )
            return
        try:
            updated = await auth_service.update_profile(
                session, user, UserUpdate(timezone=zone)
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status == 422:
                await query.edit_message_text(
                    "Esa zona horaria no es válida."
                )
            else:
                await query.edit_message_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        await query.edit_message_text(
            f"✅ Zona horaria actualizada a {updated.timezone}.\n\n"
            "Las próximas tomas se recalculan con la nueva zona.",
            reply_markup=with_home(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Configuración",
                            callback_data="menu:settings",
                        )
                    ]
                ]
            ),
        )
