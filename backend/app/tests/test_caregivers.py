"""Pruebas HTTP de los endpoints de cuidadores (Etapa 5, RF20–RF22).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 3. La base de desarrollo (`dosisalerta`) no recibe
filas de prueba: cada prueba corre dentro de una transaccion
que se revierte al final (con
`join_transaction_mode="create_savepoint"`, porque los
servicios hacen `commit` y sin savepoint el commit confirmaria
la transaccion exterior).

Flujo que se prueba (RELACIONES_CUIDADORES.md §6.3):
1. El paciente crea la invitacion y recibe el codigo una vez.
2. El cuidador presenta el codigo (vincula su identidad).
3. El paciente acepta y fija los permisos (ACTIVO).
4. El paciente cambia permisos y revoca; la auditoria registra
   cada paso (RF22).

El codigo de invitacion nunca se guarda en texto plano: las
pruebas lo leen de la respuesta de creacion (la unica vez que
se devuelve) y lo presentan despues.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.database import get_session
from app.main import create_app
from app.models.caregivers import CaregiverAuditLog, CaregiverLink

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
PASSWORD = "Prueba1234"
BOGOTA = "America/Bogota"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _test_url() -> str:
    """URL de la base de pruebas, derivada de la configuracion."""
    url = get_settings().database_url
    assert url.endswith("/dosisalerta"), f"URL inesperada: {url.rsplit('@', 1)[-1]}"
    return url[: -len("dosisalerta")] + TEST_DB


async def _create_test_db() -> None:
    settings = get_settings()
    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()


async def _drop_test_db() -> None:
    settings = get_settings()
    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def _migrated_test_db():
    """Crea la base de pruebas vacia y aplica las migraciones."""
    import asyncio

    asyncio.run(_create_test_db())
    os.environ["ALEMBIC_DATABASE_URL"] = _test_url()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield
    asyncio.run(_drop_test_db())
    os.environ.pop("ALEMBIC_DATABASE_URL", None)


@pytest.fixture(scope="session")
def test_engine(_migrated_test_db):
    # NullPool: cada conexion se crea en el bucle del test que la
    # usa y se cierra al devolverla.
    return create_async_engine(_test_url(), poolclass=NullPool)


@pytest_asyncio.fixture
async def session(test_engine):
    """Sesion por prueba, dentro de una transaccion que se revierte."""
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        sess = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield sess
        finally:
            await sess.close()
            await trans.rollback()


@pytest_asyncio.fixture
async def client(session):
    """Cliente HTTP contra la app, con la sesion de la prueba."""
    get_settings.cache_clear()
    app = create_app()

    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------


def _unique_email(prefix: str = "usuario") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _register_ok(client, email, password=PASSWORD):
    """Registra un usuario y devuelve su perfil con sus tokens."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Prueba",
            "email": email,
            "password": password,
            "timezone": BOGOTA,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _invite_ok(client, token: str) -> dict:
    """Crea una invitacion y devuelve su respuesta (con el codigo)."""
    response = await client.post("/api/v1/caregivers/invite", headers=_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


async def _audit_count(session, *, patient_id: int, action: str) -> int:
    row = await session.execute(
        select(func.count())
        .select_from(CaregiverAuditLog)
        .where(
            CaregiverAuditLog.patient_user_id == patient_id,
            CaregiverAuditLog.action == action,
        )
    )
    return row.scalar_one()


async def _link(session, link_id: int) -> CaregiverLink | None:
    result = await session.execute(
        select(CaregiverLink).where(CaregiverLink.id == link_id)
    )
    return result.scalar_one_or_none()


# ------------------------------------------------------------------
# POST /invite
# ------------------------------------------------------------------


async def test_invite_returns_code_once_and_hides_hash(client, session) -> None:
    body = await _register_ok(client, _unique_email("paciente"))
    token = body["access_token"]
    invite = await _invite_ok(client, token)
    assert invite["status"] == "INVITADO"
    assert invite["caregiver_user_id"] is None
    assert len(invite["invite_code"]) == 10
    assert invite["invite_expires_at"]
    # El codigo no se guarda en texto plano: solo el HMAC.
    link = await _link(session, invite["id"])
    assert link is not None
    assert link.invite_code_hash is not None
    assert link.invite_code_hash != invite["invite_code"]
    assert len(link.invite_code_hash) == 64
    # Ningun GET devuelve el codigo.
    listed = await client.get("/api/v1/caregivers", headers=_headers(token))
    assert listed.status_code == 200, listed.text
    assert "invite_code" not in listed.text
    assert invite["invite_code"] not in listed.text
    assert (
        await _audit_count(session, patient_id=body["user"]["id"], action="INVITE_CREATED")
        == 1
    )


async def test_invite_requires_auth(client) -> None:
    response = await client.post("/api/v1/caregivers/invite")
    assert response.status_code == 401


async def test_invite_twice_reuses_anonymous_row(client, session) -> None:
    body = await _register_ok(client, _unique_email("paciente"))
    token = body["access_token"]
    first = await _invite_ok(client, token)
    second = await _invite_ok(client, token)
    # Misma fila (no se crea otra), codigo nuevo.
    assert second["id"] == first["id"]
    assert second["invite_code"] != first["invite_code"]
    count = await session.execute(
        select(func.count())
        .select_from(CaregiverLink)
        .where(CaregiverLink.patient_user_id == body["user"]["id"])
    )
    assert count.scalar_one() == 1


# ------------------------------------------------------------------
# POST /accept-code
# ------------------------------------------------------------------


async def test_accept_code_links_identity_but_stays_invitado(client, session) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    invite = await _invite_ok(client, patient["access_token"])
    response = await client.post(
        "/api/v1/caregivers/accept-code",
        json={"code": invite["invite_code"]},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == invite["id"]
    assert data["status"] == "INVITADO"
    assert data["caregiver_user_id"] == caregiver["user"]["id"]
    assert data["caregiver_name"] == "Prueba"
    # El codigo ya no vale: la fila ya tiene cuidador.
    again = await client.post(
        "/api/v1/caregivers/accept-code",
        json={"code": invite["invite_code"]},
        headers=_headers(caregiver["access_token"]),
    )
    assert again.status_code == 404
    assert again.json()["detail"] == "Código no válido o expirado"


async def test_accept_code_wrong_code_is_generic_404(client) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    await _invite_ok(client, patient["access_token"])
    response = await client.post(
        "/api/v1/caregivers/accept-code",
        json={"code": "AAAAAAAAAA"},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Código no válido o expirado"


async def test_accept_code_own_invite_is_generic_404(client) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    invite = await _invite_ok(client, patient["access_token"])
    response = await client.post(
        "/api/v1/caregivers/accept-code",
        json={"code": invite["invite_code"]},
        headers=_headers(patient["access_token"]),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Código no válido o expirado"


async def test_accept_code_expired_is_generic_404(client, session) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    invite = await _invite_ok(client, patient["access_token"])
    link = await _link(session, invite["id"])
    assert link is not None
    link.invite_expires_at = _utcnow() - timedelta(minutes=1)
    await session.commit()
    response = await client.post(
        "/api/v1/caregivers/accept-code",
        json={"code": invite["invite_code"]},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Código no válido o expirado"


# ------------------------------------------------------------------
# POST /{id}/accept (el paciente acepta y fija permisos)
# ------------------------------------------------------------------


async def _linked_invite(client, patient, caregiver) -> dict:
    """Invitacion con la identidad del cuidador ya vinculada."""
    invite = await _invite_ok(client, patient["access_token"])
    response = await client.post(
        "/api/v1/caregivers/accept-code",
        json={"code": invite["invite_code"]},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    return invite


async def test_accept_link_activates_with_permissions(client, session) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    invite = await _linked_invite(client, patient, caregiver)
    response = await client.post(
        f"/api/v1/caregivers/{invite['id']}/accept",
        json={
            "permissions": {
                "perm_view_medications": True,
                "perm_view_history": True,
                "perm_receive_notifications": True,
            }
        },
        headers=_headers(patient["access_token"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "ACTIVO"
    assert data["perm_view_medications"] is True
    assert data["perm_view_history"] is True
    assert data["perm_receive_notifications"] is True
    assert data["perm_view_treatments"] is False
    assert data["accepted_at"]
    assert data["invite_expires_at"] is None
    link = await _link(session, invite["id"])
    assert link is not None
    assert link.invite_code_hash is None
    assert (
        await _audit_count(session, patient_id=patient["user"]["id"], action="INVITE_ACCEPTED")
        == 1
    )
    assert (
        await _audit_count(session, patient_id=patient["user"]["id"], action="PERMISSION_GRANTED")
        == 3
    )


async def test_accept_link_without_caregiver_is_409(client) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    invite = await _invite_ok(client, patient["access_token"])
    response = await client.post(
        f"/api/v1/caregivers/{invite['id']}/accept",
        json={"permissions": {}},
        headers=_headers(patient["access_token"]),
    )
    assert response.status_code == 409
    assert "código" in response.json()["detail"]


async def test_accept_link_by_other_user_is_404(client) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    other = await _register_ok(client, _unique_email("otro"))
    invite = await _linked_invite(client, patient, caregiver)
    response = await client.post(
        f"/api/v1/caregivers/{invite['id']}/accept",
        json={"permissions": {}},
        headers=_headers(other["access_token"]),
    )
    assert response.status_code == 404


async def test_accept_link_manage_without_view_is_422(client) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    invite = await _linked_invite(client, patient, caregiver)
    response = await client.post(
        f"/api/v1/caregivers/{invite['id']}/accept",
        json={"permissions": {"perm_manage_medications": True}},
        headers=_headers(patient["access_token"]),
    )
    assert response.status_code == 422


# ------------------------------------------------------------------
# PATCH /{id}/permissions
# ------------------------------------------------------------------


async def _active_link(client, patient, caregiver, permissions=None) -> dict:
    invite = await _linked_invite(client, patient, caregiver)
    response = await client.post(
        f"/api/v1/caregivers/{invite['id']}/accept",
        json={"permissions": permissions or {}},
        headers=_headers(patient["access_token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_update_permissions_grants_and_revokes_with_audit(client, session) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    link = await _active_link(
        client, patient, caregiver, {"perm_view_history": True}
    )
    response = await client.patch(
        f"/api/v1/caregivers/{link['id']}/permissions",
        json={
            "permissions": {
                "perm_view_history": False,
                "perm_view_medications": True,
            }
        },
        headers=_headers(patient["access_token"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["perm_view_history"] is False
    assert data["perm_view_medications"] is True
    assert (
        await _audit_count(session, patient_id=patient["user"]["id"], action="PERMISSION_GRANTED")
        == 2  # 1 en accept + 1 aqui (view_medications)
    )
    assert (
        await _audit_count(session, patient_id=patient["user"]["id"], action="PERMISSION_REVOKED")
        == 1  # view_history
    )
    # El detalle de auditoria no contiene datos clinicos.
    rows = await session.execute(
        select(CaregiverAuditLog).where(
            CaregiverAuditLog.patient_user_id == patient["user"]["id"],
            CaregiverAuditLog.action.in_(("PERMISSION_GRANTED", "PERMISSION_REVOKED")),
        )
    )
    for row in rows.scalars().all():
        assert row.details is not None
        assert set(row.details.keys()) == {"permission", "old", "new"}


async def test_update_permissions_by_caregiver_is_404(client) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    link = await _active_link(client, patient, caregiver)
    response = await client.patch(
        f"/api/v1/caregivers/{link['id']}/permissions",
        json={"permissions": {"perm_view_history": True}},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 404


# ------------------------------------------------------------------
# POST /{id}/revoke
# ------------------------------------------------------------------


async def test_revoke_by_patient_and_reinvite_creates_new_row(client, session) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    link = await _active_link(client, patient, caregiver)
    response = await client.post(
        f"/api/v1/caregivers/{link['id']}/revoke",
        headers=_headers(patient["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "REVOCADO"
    assert response.json()["revoked_at"]
    assert (
        await _audit_count(session, patient_id=patient["user"]["id"], action="REVOKED")
        == 1
    )
    # Revocar de nuevo es 409.
    again = await client.post(
        f"/api/v1/caregivers/{link['id']}/revoke",
        headers=_headers(patient["access_token"]),
    )
    assert again.status_code == 409
    # Reinvitar crea una fila NUEVA (la anterior queda REVOCADO).
    invite2 = await _invite_ok(client, patient["access_token"])
    assert invite2["id"] != link["id"]
    count = await session.execute(
        select(func.count())
        .select_from(CaregiverLink)
        .where(CaregiverLink.patient_user_id == patient["user"]["id"])
    )
    assert count.scalar_one() == 2


async def test_revoke_by_caregiver_ok(client, session) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    link = await _active_link(client, patient, caregiver)
    response = await client.post(
        f"/api/v1/caregivers/{link['id']}/revoke",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "REVOCADO"


async def test_revoke_by_stranger_is_404(client) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    stranger = await _register_ok(client, _unique_email("extrano"))
    link = await _active_link(client, patient, caregiver)
    response = await client.post(
        f"/api/v1/caregivers/{link['id']}/revoke",
        headers=_headers(stranger["access_token"]),
    )
    assert response.status_code == 404


# ------------------------------------------------------------------
# GET /caregivers y GET /audit
# ------------------------------------------------------------------


async def test_list_links_separates_patient_and_caregiver(client) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    link = await _active_link(client, patient, caregiver)
    as_patient = await client.get(
        "/api/v1/caregivers", headers=_headers(patient["access_token"])
    )
    assert as_patient.status_code == 200, as_patient.text
    data = as_patient.json()
    assert len(data["as_patient"]) == 1
    assert data["as_patient"][0]["id"] == link["id"]
    assert data["as_patient"][0]["caregiver_name"] == "Prueba"
    assert data["as_caregiver"] == []
    as_caregiver = await client.get(
        "/api/v1/caregivers", headers=_headers(caregiver["access_token"])
    )
    assert as_caregiver.status_code == 200, as_caregiver.text
    data = as_caregiver.json()
    assert data["as_patient"] == []
    assert len(data["as_caregiver"]) == 1
    assert data["as_caregiver"][0]["patient_name"] == "Prueba"


async def test_audit_lists_actions_for_patient(client) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    await _active_link(
        client, patient, caregiver, {"perm_view_history": True}
    )
    response = await client.get(
        "/api/v1/caregivers/audit", headers=_headers(patient["access_token"])
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] >= 3  # INVITE_CREATED + INVITE_ACCEPTED + PERMISSION_GRANTED
    actions = [item["action"] for item in data["items"]]
    assert "INVITE_CREATED" in actions
    assert "INVITE_ACCEPTED" in actions
    assert "PERMISSION_GRANTED" in actions
    # El cuidador no ve la auditoria del paciente (es su propio
    # listado: vacio si nadie actuo sobre sus datos).
    other = await client.get(
        "/api/v1/caregivers/audit", headers=_headers(caregiver["access_token"])
    )
    assert other.status_code == 200, other.text
    assert other.json()["total"] == 0


# ------------------------------------------------------------------
# patient_id inexistente: 403, no 500 (Etapa 7)
# ------------------------------------------------------------------


async def test_nonexistent_patient_id_is_403_not_500(client) -> None:
    """Un patient_id inexistente da 403 en todos los modulos, no 500.

    Regresion (Etapa 7): `audit_denied` insertaba en
    `caregiver_audit_log` con FK a `users` y el paciente
    inexistente reventaba con ForeignKeyViolationError (500).
    `resolve_actor` y `_reject_caregiver_mutation` deniegan sin
    intentar el registro, y la respuesta no distingue un paciente
    real sin vinculo de uno inexistente (403 en ambos casos).
    """
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    await _active_link(client, patient, caregiver, {"perm_view_medications": True})
    ghost = 999999
    headers = _headers(caregiver["access_token"])
    for method, path in [
        ("GET", f"/api/v1/medications?patient_id={ghost}"),
        ("GET", f"/api/v1/treatments?patient_id={ghost}"),
        ("GET", f"/api/v1/reminders/history?patient_id={ghost}"),
        ("GET", f"/api/v1/stats/compliance?patient_id={ghost}"),
    ]:
        response = await client.request(method, path, headers=headers)
        assert response.status_code == 403, (method, path, response.text)
    # Mutacion con paciente inexistente: tambien 403, no 500.
    response = await client.patch(
        f"/api/v1/treatments/1?patient_id={ghost}",
        json={"title": "Fantasma"},
        headers=headers,
    )
    assert response.status_code == 403, response.text
