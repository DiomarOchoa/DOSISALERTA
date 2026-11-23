"""Seccion "Mis tratamientos" (Fase 6, RF16/RF18).

Muestra la lista real de tratamientos y el detalle de cada uno,
con el mismo servicio y validaciones que la web (RF18). Acciones:

- "Pausar" / "Reanudar" (cambia el estado; pausar cancela los
  recordatorios PENDIENTE futuros y conserva el historial).
- "Cancelar" (con confirmacion; los recordatorios pendientes se
  cancelan y el historial se conserva, RF08).
- "Completar" (con confirmacion).

Crear un tratamiento completo (varios medicamentos, dosis y
horarios) se hace desde la web: el flujo por chat es demasiado
largo para un adulto mayor y la web ya lo cubre con validaciones.
"""

from __future__ import annotations

from decimal import Decimal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.context import linked_session
from app.bot.keyboards import with_home

_ACTIONS = {
    "PAUSADO": ("⏸️ Pausar", "treat:pause:"),
    "ACTIVO": ("▶️ Reanudar", "treat:resume:"),
    "CANCELADO": ("🚫 Cancelar", "treat:cancel:"),
    "COMPLETADO": ("✅ Completar", "treat:complete:"),
}


def _dose_text(dose_amount: Decimal, dose_unit: str) -> str:
    return f"{dose_amount.normalize():f} {dose_unit}"


def _detail_text(treatment) -> str:
    """Detalle de un tratamiento."""
    lines = [f"🗂️ {treatment.title}", "", f"Estado: {treatment.status}"]
    lines.append(f"Inicio: {treatment.start_date}")
    if treatment.end_date:
        lines.append(f"Fin: {treatment.end_date}")
    if treatment.notes:
        lines.append(f"Notas: {treatment.notes}")
    lines.append("")
    lines.append("Medicamentos:")
    for link in treatment.medications:
        if not link.is_active:
            continue
        lines.append(
            f"• {link.medication_name} — "
            f"{_dose_text(link.dose_amount, link.dose_unit)}"
        )
    return "\n".join(lines)


async def show_treatments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista real de tratamientos (boton del menu o /tratamientos)."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    from app.services import treatment_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        treatments = await treatment_service.list_treatments(session, user)
        lines = ["🗂️ Mis tratamientos", ""]
        rows: list[list[InlineKeyboardButton]] = []
        for treatment in treatments:
            lines.append(f"• {treatment.title} — {treatment.status}")
            rows.append(
                [
                    InlineKeyboardButton(
                        f"Ver {treatment.title}",
                        callback_data=f"treat:{treatment.id}",
                    )
                ]
            )
        if not treatments:
            lines.append("No tienes tratamientos.")
        lines.append("")
        lines.append(
            "Para crear un tratamiento nuevo, usa la web de DosisAlerta."
        )
        text = "\n".join(lines)
        keyboard = with_home(rows)
        if query is not None:
            await query.edit_message_text(text, reply_markup=keyboard)
        elif update.message is not None:
            await update.message.reply_text(text, reply_markup=keyboard)


async def show_treatment_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detalle real de un tratamiento (boton Ver)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    rest = data.removeprefix("treat:")
    if not rest.isdigit():
        await query.edit_message_text("No encontré ese tratamiento.")
        return
    treatment_id = int(rest)
    from app.services import treatment_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            treatment = await treatment_service.get_treatment(
                session, user, treatment_id
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status in (404, 403):
                await query.edit_message_text("No encontré ese tratamiento.")
            else:
                await query.edit_message_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        rows: list[list[InlineKeyboardButton]] = []
        if treatment.status == "ACTIVO":
            rows.append(
                [
                    InlineKeyboardButton(
                        "⏸️ Pausar", callback_data=f"treat:pause:{treatment.id}"
                    ),
                    InlineKeyboardButton(
                        "🚫 Cancelar",
                        callback_data=f"treat:cancel:{treatment.id}",
                    ),
                ]
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        "✅ Completar",
                        callback_data=f"treat:complete:{treatment.id}",
                    )
                ]
            )
        elif treatment.status == "PAUSADO":
            rows.append(
                [
                    InlineKeyboardButton(
                        "▶️ Reanudar",
                        callback_data=f"treat:resume:{treatment.id}",
                    ),
                    InlineKeyboardButton(
                        "🚫 Cancelar",
                        callback_data=f"treat:cancel:{treatment.id}",
                    ),
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    "⬅️ Mis tratamientos", callback_data="menu:treatments"
                )
            ]
        )
        await query.edit_message_text(
            _detail_text(treatment), reply_markup=with_home(rows)
        )


def _confirm_keyboard(treatment_id: int, action: str) -> InlineKeyboardMarkup:
    """Confirmacion de un cambio de estado (Pausar/Cancelar/Completar)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Sí, confirmar",
                    callback_data=f"treat:{action}_confirm:{treatment_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancelar", callback_data=f"treat:{treatment_id}"
                )
            ],
        ]
    )


async def ask_status_change(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pide confirmacion antes de pausar, cancelar o completar."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    # treat:pause:<id> | treat:cancel:<id> | treat:complete:<id>
    parts = data.split(":")
    if len(parts) != 3 or parts[1] not in ("pause", "cancel", "complete"):
        await query.edit_message_text("No encontré ese tratamiento.")
        return
    action = parts[1]
    if not parts[2].isdigit():
        await query.edit_message_text("No encontré ese tratamiento.")
        return
    treatment_id = int(parts[2])
    from app.services import treatment_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            treatment = await treatment_service.get_treatment(
                session, user, treatment_id
            )
        except Exception:
            await query.edit_message_text("No encontré ese tratamiento.")
            return
        messages = {
            "pause": (
                f"¿Pausar «{treatment.title}»?\n\n"
                "Sus próximos recordatorios se cancelarán. "
                "El historial no se borra y podrás reanudarlo cuando quieras."
            ),
            "cancel": (
                f"¿Cancelar «{treatment.title}»?\n\n"
                "Sus próximos recordatorios se cancelarán. "
                "El historial se conserva y no podrás reanudarlo."
            ),
            "complete": (
                f"¿Marcar «{treatment.title}» como completado?\n\n"
                "Sus próximos recordatorios se cancelarán. "
                "El historial se conserva."
            ),
        }
        await query.edit_message_text(
            messages[action],
            reply_markup=_confirm_keyboard(treatment_id, action),
        )


async def confirm_status_change(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Aplica el cambio de estado (confirmacion)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    parts = data.split(":")
    if len(parts) != 3:
        await query.edit_message_text("No encontré ese tratamiento.")
        return
    raw = parts[1]
    if raw.endswith("_confirm"):
        action = raw.removesuffix("_confirm")
    elif raw == "resume":
        action = "resume"
    else:
        await query.edit_message_text("No encontré ese tratamiento.")
        return
    if action not in ("pause", "resume", "cancel", "complete"):
        await query.edit_message_text("No encontré ese tratamiento.")
        return
    if not parts[2].isdigit():
        await query.edit_message_text("No encontré ese tratamiento.")
        return
    treatment_id = int(parts[2])
    from app.services import treatment_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            if action == "pause":
                treatment = await treatment_service.pause_treatment(
                    session, user, treatment_id
                )
                done = "pausado"
            elif action == "resume":
                treatment = await treatment_service.resume_treatment(
                    session, user, treatment_id
                )
                done = "reanudado"
            elif action == "cancel":
                treatment = await treatment_service.cancel_treatment(
                    session, user, treatment_id
                )
                done = "cancelado"
            else:
                treatment = await treatment_service.complete_treatment(
                    session, user, treatment_id
                )
                done = "completado"
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            detail = getattr(exc, "detail", "")
            if status in (404, 403):
                await query.edit_message_text("No encontré ese tratamiento.")
            elif status == 400:
                await query.edit_message_text(f"⚠️ {detail}")
            else:
                await query.edit_message_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        await query.edit_message_text(
            f"✅ «{treatment.title}» {done}. Estado: {treatment.status}.",
            reply_markup=with_home(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Mis tratamientos",
                            callback_data="menu:treatments",
                        )
                    ]
                ]
            ),
        )
