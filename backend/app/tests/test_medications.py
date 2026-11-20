"""Pruebas de integracion de medicamentos (Fase 4, RF04).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 3. La base de desarrollo (`dosisalerta`) no recibe
filas de prueba: cada prueba corre dentro de una transaccion
que se revierte al final (con
`join_transaction_mode="create_savepoint"`, porque los
servicios hacen `commit` y sin savepoint el commit confirmaria
la transaccion exterior).

Las llamadas HTTP usan `httpx.AsyncClient` + `ASGITransport`
(en el mismo bucle de eventos que la prueba), para que la
sesion de la prueba —ligada a ese bucle— funcione dentro de
cada peticion.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.database import get_session
from app.main import create_app
from app.models import Medication

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
PASSWORD = "clave-segura-123"


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
    """Sesion por prueba, dentro de una transaccion que se revierte.

    `join_transaction_mode="create_savepoint"`: la sesion se une
    a la transaccion exterior mediante un savepoint, asi que los
    `commit` de los servicios solo liberan el savepoint y la
    transaccion exterior sigue pudiendo revertirse al final.
    """
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
            "timezone": "America/Bogota",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_medication_ok(client, token, payload):
    """Crea un medicamento y devuelve su cuerpo (201)."""
    response = await client.post(
        "/api/v1/medications", json=payload, headers=_headers(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------------------
# 1. Crear
# ------------------------------------------------------------------


async def test_create_medication_ok(client):
    """Crear con todos los campos -> 201, activo, con id."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created = await _create_medication_ok(
        client,
        token,
        {
            "name": "Amoxicilina",
            "presentation": "Capsulas",
            "concentration": "500 mg",
            "unit": "capsula",
            "notes": "Con alimentos",
        },
    )
    assert created["id"]
    assert created["name"] == "Amoxicilina"
    assert created["presentation"] == "Capsulas"
    assert created["concentration"] == "500 mg"
    assert created["unit"] == "capsula"
    assert created["notes"] == "Con alimentos"
    assert created["is_active"] is True
    assert created["created_at"]
    assert created["updated_at"]


async def test_create_medication_optional_fields_null(client):
    """Crear solo con el nombre -> 201, opcionales en null."""
    body = await _register_ok(client, _unique_email())
    created = await _create_medication_ok(
        client, body["access_token"], {"name": "Paracetamol"}
    )
    assert created["name"] == "Paracetamol"
    assert created["presentation"] is None
    assert created["concentration"] is None
    assert created["unit"] is None
    assert created["notes"] is None


async def test_create_medication_blank_name_422(client):
    """Nombre solo con espacios -> 422."""
    body = await _register_ok(client, _unique_email())
    response = await client.post(
        "/api/v1/medications",
        json={"name": "   "},
        headers=_headers(body["access_token"]),
    )
    assert response.status_code == 422


async def test_create_medication_name_too_long_422(client):
    """Nombre de mas de 150 caracteres -> 422."""
    body = await _register_ok(client, _unique_email())
    response = await client.post(
        "/api/v1/medications",
        json={"name": "A" * 151},
        headers=_headers(body["access_token"]),
    )
    assert response.status_code == 422


async def test_create_medication_unauthenticated_401(client):
    """Sin token -> 401."""
    response = await client.post("/api/v1/medications", json={"name": "Amoxicilina"})
    assert response.status_code == 401


# ------------------------------------------------------------------
# 2. Listar
# ------------------------------------------------------------------


async def test_list_medications_only_own(client):
    """El listado solo trae los medicamentos propios, por nombre."""
    user_a = await _register_ok(client, _unique_email("a"))
    user_b = await _register_ok(client, _unique_email("b"))
    await _create_medication_ok(client, user_a["access_token"], {"name": "Zinc"})
    await _create_medication_ok(client, user_a["access_token"], {"name": "Amoxicilina"})
    await _create_medication_ok(client, user_b["access_token"], {"name": "Paracetamol"})
    response = await client.get(
        "/api/v1/medications", headers=_headers(user_a["access_token"])
    )
    assert response.status_code == 200, response.text
    names = [item["name"] for item in response.json()]
    assert names == ["Amoxicilina", "Zinc"]


async def test_list_medications_excludes_inactive_by_default(client, session):
    """El listado por defecto no trae desactivados; con
    `is_active=false` trae solo esos."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    active = await _create_medication_ok(client, token, {"name": "Amoxicilina"})
    inactive = await _create_medication_ok(client, token, {"name": "Ibuprofeno"})
    response = await client.delete(
        f"/api/v1/medications/{inactive['id']}", headers=_headers(token)
    )
    assert response.status_code == 200
    response = await client.get("/api/v1/medications", headers=_headers(token))
    assert [item["name"] for item in response.json()] == ["Amoxicilina"]
    response = await client.get(
        "/api/v1/medications?is_active=false", headers=_headers(token)
    )
    assert [item["name"] for item in response.json()] == ["Ibuprofeno"]
    # El desactivado sigue existiendo en la BD (no hay borrado fisico).
    result = await session.execute(
        select(Medication).where(Medication.id == inactive["id"])
    )
    assert result.scalar_one().is_active is False
    assert active["id"]


async def test_list_medications_unauthenticated_401(client):
    """Sin token -> 401."""
    response = await client.get("/api/v1/medications")
    assert response.status_code == 401


# ------------------------------------------------------------------
# 3. Ver uno
# ------------------------------------------------------------------


async def test_get_medication_ok(client):
    """Ver un medicamento propio -> 200 con todos los campos."""
    body = await _register_ok(client, _unique_email())
    created = await _create_medication_ok(
        client, body["access_token"], {"name": "Amoxicilina", "unit": "capsula"}
    )
    response = await client.get(
        f"/api/v1/medications/{created['id']}",
        headers=_headers(body["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == created["id"]
    assert response.json()["name"] == "Amoxicilina"


async def test_get_medication_not_found_404(client):
    """Id inexistente -> 404."""
    body = await _register_ok(client, _unique_email())
    response = await client.get(
        "/api/v1/medications/999999", headers=_headers(body["access_token"])
    )
    assert response.status_code == 404


async def test_get_medication_other_user_403(client):
    """Medicamento de otro usuario -> 403 (no 404: existe)."""
    user_a = await _register_ok(client, _unique_email("a"))
    user_b = await _register_ok(client, _unique_email("b"))
    created = await _create_medication_ok(
        client, user_a["access_token"], {"name": "Amoxicilina"}
    )
    response = await client.get(
        f"/api/v1/medications/{created['id']}",
        headers=_headers(user_b["access_token"]),
    )
    assert response.status_code == 403


# ------------------------------------------------------------------
# 4. Editar
# ------------------------------------------------------------------


async def test_update_medication_partial(client):
    """PATCH parcial: solo cambia lo enviado; lo demas queda igual."""
    body = await _register_ok(client, _unique_email())
    created = await _create_medication_ok(
        client,
        body["access_token"],
        {"name": "Amoxicilina", "concentration": "500 mg", "unit": "capsula"},
    )
    response = await client.patch(
        f"/api/v1/medications/{created['id']}",
        json={"name": "Amoxicilina forte"},
        headers=_headers(body["access_token"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["name"] == "Amoxicilina forte"
    assert data["concentration"] == "500 mg"
    assert data["unit"] == "capsula"
    assert data["is_active"] is True


async def test_update_medication_empty_payload_422(client):
    """PATCH sin campos -> 422."""
    body = await _register_ok(client, _unique_email())
    created = await _create_medication_ok(
        client, body["access_token"], {"name": "Amoxicilina"}
    )
    response = await client.patch(
        f"/api/v1/medications/{created['id']}",
        json={},
        headers=_headers(body["access_token"]),
    )
    assert response.status_code == 422


async def test_update_medication_not_found_404(client):
    """PATCH a id inexistente -> 404."""
    body = await _register_ok(client, _unique_email())
    response = await client.patch(
        "/api/v1/medications/999999",
        json={"name": "Otro"},
        headers=_headers(body["access_token"]),
    )
    assert response.status_code == 404


async def test_update_medication_other_user_403(client):
    """PATCH a medicamento de otro usuario -> 403."""
    user_a = await _register_ok(client, _unique_email("a"))
    user_b = await _register_ok(client, _unique_email("b"))
    created = await _create_medication_ok(
        client, user_a["access_token"], {"name": "Amoxicilina"}
    )
    response = await client.patch(
        f"/api/v1/medications/{created['id']}",
        json={"name": "Otro"},
        headers=_headers(user_b["access_token"]),
    )
    assert response.status_code == 403


# ------------------------------------------------------------------
# 5. Desactivar
# ------------------------------------------------------------------


async def test_deactivate_medication_ok(client):
    """DELETE desactiva (logico): 200 con is_active=false; sigue
    consultable por id pero no sale en el listado por defecto."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created = await _create_medication_ok(client, token, {"name": "Amoxicilina"})
    response = await client.delete(
        f"/api/v1/medications/{created['id']}", headers=_headers(token)
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert response.json()["name"] == "Amoxicilina"
    response = await client.get(
        f"/api/v1/medications/{created['id']}", headers=_headers(token)
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    response = await client.get("/api/v1/medications", headers=_headers(token))
    assert response.json() == []


async def test_deactivate_medication_not_found_404(client):
    """DELETE a id inexistente -> 404."""
    body = await _register_ok(client, _unique_email())
    response = await client.delete(
        "/api/v1/medications/999999", headers=_headers(body["access_token"])
    )
    assert response.status_code == 404


async def test_deactivate_medication_other_user_403(client):
    """DELETE a medicamento de otro usuario -> 403."""
    user_a = await _register_ok(client, _unique_email("a"))
    user_b = await _register_ok(client, _unique_email("b"))
    created = await _create_medication_ok(
        client, user_a["access_token"], {"name": "Amoxicilina"}
    )
    response = await client.delete(
        f"/api/v1/medications/{created['id']}",
        headers=_headers(user_b["access_token"]),
    )
    assert response.status_code == 403
