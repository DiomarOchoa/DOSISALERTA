"""Seccion "Mi familiar o cuidador" (Fase 6, RF20–RF22).

Muestra los vinculos reales del usuario, como paciente y como
cuidador, con el mismo servicio y validaciones que la web:

- "➕ Invitar cuidador": crea la invitacion y muestra el codigo
  UNA SOLA VEZ (10 caracteres, caduca en 15 minutos).
- Invitacion pendiente (el cuidador ya presento el codigo con
  /vincular_cuidador): el paciente elige los 8 permisos, uno a
  uno, y confirma con "Aceptar y activar".
- Vinculo activo: "Revocar" (con confirmacion; inmediato).
- Como cuidador: la lista de pacientes y el estado de cada
  vinculo (solo lectura desde aqui).

Los permisos empiezan todos en NO. Gestionar exige poder ver:
al activar un permiso de gestion se activa su lectura, y al
quitar la lectura se quita su gestion. El cuidador NUNCA puede
confirmar tomas (sin permiso para ello).
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.context import linked_session
from app.bot.keyboards import with_home

_PERMISSION_LABELS = (
    "Ver medicamentos",
    "Ver tratamientos",
    "Ver horarios",
    "Ver próximas tomas",
    "Ver historial",
    "Recibir avisos",
    "Gestionar medicamentos",
    "Gestionar horarios",
)
# Gestionar medicamentos (6) exige ver medicamentos (0);
# gestionar horarios (7) exige ver horarios (2).
_MANAGE_TO_VIEW = {6: 0, 7: 2}
_VIEW_TO_MANAGE = {0: 6, 2: 7}


def _bits_to_permissions(bits: str):
    """'01010000' -> CaregiverPermissions con los 8 permisos."""
    from app.models.caregivers import CAREGIVER_PERMISSIONS
    from app.schemas.caregivers import CaregiverPermissions

    values = {
        name: (bits[i] == "1")
        for i, name in enumerate(CAREGIVER_PERMISSIONS)
    }
    return CaregiverPermissions(**values)


def _permissions_to_bits(link) -> str:
    from app.models.caregivers import CAREGIVER_PERMISSIONS

    return "".join(
        "1" if getattr(link, name) else "0" for name in CAREGIVER_PERMISSIONS
    )


def _toggle_bits(bits: str, idx: int) -> str:
    """Cambia el bit idx, aplicando gestionar-exige-ver."""
    chars = list(bits)
    chars[idx] = "0" if chars[idx] == "1" else "1"
    if chars[idx] == "1" and idx in _MANAGE_TO_VIEW:
        chars[_MANAGE_TO_VIEW[idx]] = "1"
    if chars[idx] == "0" and idx in _VIEW_TO_MANAGE:
        chars[_VIEW_TO_MANAGE[idx]] = "0"
    return "".join(chars)


async def _get_link(session, user, link_id: int):
    """Un vinculo del usuario (como paciente o como cuidador)."""
    from app.services import caregiver_service

    links = await caregiver_service.list_links(session, user)
    for link in list(links.as_patient) + list(links.as_caregiver):
        if link.id == link_id:
            return link
    return None


def _picker_keyboard(link_id: int, bits: str) -> InlineKeyboardMarkup:
    """8 botones de permiso (✅/⬜) + aceptar + cancelar."""
    rows = []
    for idx, label in enumerate(_PERMISSION_LABELS):
        mark = "✅" if bits[idx] == "1" else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{mark} {label}",
                    callback_data=f"cg:toggle:{link_id}:{bits}:{idx}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "✅ Aceptar y activar",
                callback_data=f"cg:accept_confirm:{link_id}:{bits}",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "❌ Cancelar", callback_data="menu:caregivers"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


async def show_caregivers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Vinculos reales (boton del menu)."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    from app.services import caregiver_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        links = await caregiver_service.list_links(session, user)
        lines = ["👨‍👩‍👧 Mi familiar o cuidador", ""]
        rows: list[list[InlineKeyboardButton]] = []
        if links.as_patient:
            lines.append("Tus cuidadores:")
            for link in links.as_patient:
                name = link.caregiver_name or "Cuidador sin vincular"
                lines.append(f"• {name} — {link.status}")
                if link.status == "INVITADO" and link.caregiver_user_id:
                    rows.append(
                        [
                            InlineKeyboardButton(
                                f"✅ Aceptar a {name}",
                                callback_data=f"cg:accept:{link.id}",
                            )
                        ]
                    )
                elif link.status == "ACTIVO":
                    rows.append(
                        [
                            InlineKeyboardButton(
                                f"🚫 Revocar a {name}",
                                callback_data=f"cg:revoke:{link.id}",
                            )
                        ]
                    )
            lines.append("")
        if links.as_caregiver:
            lines.append("Eres cuidador de:")
            for link in links.as_caregiver:
                name = link.patient_name or "Paciente"
                lines.append(f"• {name} — {link.status}")
                if link.status == "ACTIVO":
                    rows.append(
                        [
                            InlineKeyboardButton(
                                f"🚫 Dejar de cuidar a {name}",
                                callback_data=f"cg:revoke:{link.id}",
                            )
                        ]
                    )
            lines.append("")
        if not links.as_patient and not links.as_caregiver:
            lines.append(
                "Aún no tienes cuidadores ni eres cuidador de nadie."
            )
            lines.append("")
        lines.append(
            "Para invitar a un cuidador, pulsa el botón y comparte "
            "el código con esa persona."
        )
        rows.append(
            [
                InlineKeyboardButton(
                    "➕ Invitar cuidador", callback_data="cg:invite"
                )
            ]
        )
        text = "\n".join(lines)
        keyboard = with_home(rows)
        if query is not None:
            await query.edit_message_text(text, reply_markup=keyboard)
        elif update.message is not None:
            await update.message.reply_text(text, reply_markup=keyboard)


async def invite_caregiver(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Crea la invitacion y muestra el codigo UNA SOLA VEZ."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    from app.services import caregiver_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        invite = await caregiver_service.create_invite(session, user)
        await query.edit_message_text(
            "👨‍👩‍👧 Invitación creada\n\n"
            f"Código: {invite.invite_code}\n\n"
            "Compártelo con tu cuidador. El código caduca en "
            "15 minutos y no se volverá a mostrar.\n\n"
            "Tu cuidador debe vincular su cuenta con /vincular y "
            "luego presentar el código con /vincular_cuidador.",
            reply_markup=with_home(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Mis cuidadores",
                            callback_data="menu:caregivers",
                        )
                    ]
                ]
            ),
        )


async def show_permission_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Selector de permisos para aceptar una invitacion."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    rest = data.removeprefix("cg:accept:")
    if not rest.isdigit():
        await query.edit_message_text("No encontré esa invitación.")
        return
    link_id = int(rest)
    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        link = await _get_link(session, user, link_id)
        if link is None:
            await query.edit_message_text("No encontré esa invitación.")
            return
        if link.status != "INVITADO":
            await query.edit_message_text(
                "Esa invitación ya no está pendiente."
            )
            return
        name = link.caregiver_name or "tu cuidador"
        await query.edit_message_text(
            f"✅ Aceptar a {name}\n\n"
            "Elige qué puede hacer tu cuidador. Todos los "
            "permisos empiezan desactivados.\n\n"
            "Gestionar exige poder ver: al activar un permiso de "
            "gestión se activa su lectura.",
            reply_markup=_picker_keyboard(link_id, "00000000"),
        )


async def toggle_permission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Activa/desactiva un permiso del selector (sin guardar)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    # cg:toggle:<id>:<bits>:<idx>
    parts = data.split(":")
    if len(parts) != 5 or not parts[2].isdigit() or not parts[4].isdigit():
        await query.edit_message_text("No encontré esa invitación.")
        return
    link_id = int(parts[2])
    bits = parts[3]
    idx = int(parts[4])
    if len(bits) != 8 or not (0 <= idx < 8):
        await query.edit_message_text("No encontré esa invitación.")
        return
    new_bits = _toggle_bits(bits, idx)
    await query.edit_message_text(
        "✅ Aceptar cuidador\n\n"
        "Elige qué puede hacer tu cuidador. Todos los permisos "
        "empiezan desactivados.\n\n"
        "Gestionar exige poder ver: al activar un permiso de "
        "gestión se activa su lectura.",
        reply_markup=_picker_keyboard(link_id, new_bits),
    )


async def confirm_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Acepta la invitacion con los permisos elegidos."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    # cg:accept_confirm:<id>:<bits>
    parts = data.split(":")
    if len(parts) != 4 or not parts[2].isdigit():
        await query.edit_message_text("No encontré esa invitación.")
        return
    link_id = int(parts[2])
    bits = parts[3]
    if len(bits) != 8:
        await query.edit_message_text("No encontré esa invitación.")
        return
    from app.services import caregiver_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            link = await caregiver_service.accept_link(
                session, user, link_id, _bits_to_permissions(bits)
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            detail = getattr(exc, "detail", "")
            if status in (404, 409):
                await query.edit_message_text(f"⚠️ {detail}")
            elif status == 422:
                await query.edit_message_text(
                    "⚠️ Esa combinación de permisos no es válida."
                )
            else:
                await query.edit_message_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        name = link.caregiver_name or "tu cuidador"
        granted = [
            label
            for idx, label in enumerate(_PERMISSION_LABELS)
            if bits[idx] == "1"
        ]
        lines = [f"✅ {name} ahora es tu cuidador.", ""]
        if granted:
            lines.append("Permisos concedidos:")
            for label in granted:
                lines.append(f"• {label}")
        else:
            lines.append("Sin permisos concedidos.")
        lines.append("")
        lines.append("Puedes cambiarlos o revocarlos cuando quieras.")
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=with_home(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Mis cuidadores",
                            callback_data="menu:caregivers",
                        )
                    ]
                ]
            ),
        )


async def ask_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pide confirmacion antes de revocar un vinculo."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    rest = data.removeprefix("cg:revoke:")
    if not rest.isdigit():
        await query.edit_message_text("No encontré ese vínculo.")
        return
    link_id = int(rest)
    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        link = await _get_link(session, user, link_id)
        if link is None:
            await query.edit_message_text("No encontré ese vínculo.")
            return
        if link.status == "REVOCADO":
            await query.edit_message_text("Ese vínculo ya está revocado.")
            return
        if link.patient_user_id == user.id:
            other = link.caregiver_name or "tu cuidador"
            text = f"¿Revocar a {other}?\n\nDejará de ver tus datos de inmediato."
        else:
            other = link.patient_name or "el paciente"
            text = f"¿Dejar de cuidar a {other}?\n\nDejarás de ver sus datos de inmediato."
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Sí, revocar",
                            callback_data=f"cg:revoke_confirm:{link_id}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ Cancelar",
                            callback_data="menu:caregivers",
                        )
                    ],
                ]
            ),
        )


async def confirm_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Revoca el vinculo (confirmacion)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    rest = data.removeprefix("cg:revoke_confirm:")
    if not rest.isdigit():
        await query.edit_message_text("No encontré ese vínculo.")
        return
    link_id = int(rest)
    from app.services import caregiver_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            await caregiver_service.revoke_link(session, user, link_id)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status in (404, 409):
                await query.edit_message_text(
                    f"⚠️ {getattr(exc, 'detail', 'No se pudo revocar.')}"
                )
            else:
                await query.edit_message_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        await query.edit_message_text(
            "✅ Vínculo revocado.",
            reply_markup=with_home(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Mis cuidadores",
                            callback_data="menu:caregivers",
                        )
                    ]
                ]
            ),
        )
