"""Pruebas de vinculacion de Telegram (Etapa 6, RF15).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 3. La base de desarrollo (`dosisalerta`) no recibe
filas de prueba: cada prueba corre dentro de una transaccion
que se revierte al final (con
`join_transaction_mode="create_savepoint"`, porque los
servicios hacen `commit` y sin savepoint el commit confirmaria
la transaccion exterior).

RF15: vinculacion por codigo de un solo uso (10 caracteres con
`secrets`, HMAC-SHA256 con secreto dedicado, vencimiento de 15
minutos, 5 fallos por `chat_id` en 15 minutos, mensaje generico
ante cualquier fallo) y desvinculacion desde la web.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.database import get_session
from app.main import create_app
from app.models.telegram import TelegramAccount, TelegramLinkAttempt
from app.models.users import User
from app.services import telegram_link_service

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
PASSWORD = "Prueba1234"
BOGOTA = "America/Bogota"

_CODE_RE = re.compile(r"^[A-Z2-9]{10}$")
_GENERIC_ERROR = "Código no válido o expirado"


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


async def _user(session, user_id: int) -> User:
    user = await session.get(User, user_id)
    assert user is not None
    return user


async def _account(session, user_id: int) -> TelegramAccount | None:
    result = await session.execute(
        select(TelegramAccount).where(TelegramAccount.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _attempts(session, chat_id: int) -> list[TelegramLinkAttempt]:
    result = await session.execute(
        select(TelegramLinkAttempt)
        .where(TelegramLinkAttempt.chat_id == chat_id)
        .order_by(TelegramLinkAttempt.id)
    )
    return list(result.scalars().all())


# ------------------------------------------------------------------
# POST /telegram/link + GET /telegram/status
# ------------------------------------------------------------------


async def test_link_genera_codigo_y_status_pendiente(client, session):
    """POST /link devuelve el codigo una sola vez (201)."""
    reg = await _register_ok(client, _unique_email())
    token = reg["access_token"]

    status = await client.get("/api/v1/telegram/status", headers=_headers(token))
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "SIN_VINCULAR"
    assert status.json()["has_pending_code"] is False

    response = await client.post("/api/v1/telegram/link", headers=_headers(token))
    assert response.status_code == 201, response.text
    body = response.json()
    assert _CODE_RE.match(body["code"]), body["code"]
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(minutes=14) < expires - _utcnow() < timedelta(minutes=16)

    status = await client.get("/api/v1/telegram/status", headers=_headers(token))
    assert status.json()["status"] == "PENDIENTE"
    assert status.json()["has_pending_code"] is True
    # El codigo nunca se devuelve por el estado.
    assert "code" not in status.json()

    account = await _account(session, reg["user"]["id"])
    assert account is not None
    assert account.link_code_hash is not None
    assert account.link_code_hash != body["code"]
    assert len(account.link_code_hash) == 64


async def test_link_sin_sesion_401(client):
    """Sin token, generar codigo es 401."""
    response = await client.post("/api/v1/telegram/link")
    assert response.status_code == 401


async def test_link_regenera_invalida_el_anterior(client, session):
    """Un segundo codigo invalida el primero (solo vale el ultimo)."""
    reg = await _register_ok(client, _unique_email())
    token = reg["access_token"]
    user = await _user(session, reg["user"]["id"])

    first = await client.post("/api/v1/telegram/link", headers=_headers(token))
    first_code = first.json()["code"]
    second = await client.post("/api/v1/telegram/link", headers=_headers(token))
    second_code = second.json()["code"]
    assert first_code != second_code

    # El primero ya no vincula (404 generico).
    with pytest.raises(HTTPException) as excinfo:
        await telegram_link_service.confirm_link(
            session, first_code, telegram_user_id=111, chat_id=111
        )
    assert excinfo.value.status_code == 404
    assert _GENERIC_ERROR in str(excinfo.value.detail)

    # El segundo si vincula.
    account = await telegram_link_service.confirm_link(
        session, second_code, telegram_user_id=111, chat_id=111
    )
    assert account.status == "VINCULADA"
    assert account.chat_id == 111
    assert account.telegram_user_id == 111


# ------------------------------------------------------------------
# confirm_link (bot /vincular)
# ------------------------------------------------------------------


async def test_confirm_vincula_y_limpia_hash(client, session):
    """Codigo valido vincula: VINCULADA, chat y hash a NULL."""
    reg = await _register_ok(client, _unique_email())
    token = reg["access_token"]
    user = await _user(session, reg["user"]["id"])

    created = await telegram_link_service.create_link_code(session, user)
    account = await telegram_link_service.confirm_link(
        session, created.code, telegram_user_id=222, chat_id=222,
        username="paciente_bot",
    )
    assert account.status == "VINCULADA"
    assert account.telegram_user_id == 222
    assert account.chat_id == 222
    assert account.username == "paciente_bot"
    assert account.linked_at is not None
    assert account.link_code_hash is None
    assert account.link_expires_at is None

    status = await client.get("/api/v1/telegram/status", headers=_headers(token))
    assert status.json()["status"] == "VINCULADA"
    assert status.json()["telegram_username"] == "paciente_bot"
    assert status.json()["has_pending_code"] is False

    attempts = await _attempts(session, 222)
    assert len(attempts) == 1
    assert attempts[0].success is True
    assert attempts[0].reason is None


async def test_confirm_codigo_erroneo_404_generico(client, session):
    """Codigo inexistente: 404 generico, intento registrado."""
    reg = await _register_ok(client, _unique_email())
    user = await _user(session, reg["user"]["id"])
    await telegram_link_service.create_link_code(session, user)

    with pytest.raises(HTTPException) as excinfo:
        await telegram_link_service.confirm_link(
            session, "ZZZZZZZZZZ", telegram_user_id=333, chat_id=333
        )
    assert excinfo.value.status_code == 404
    assert _GENERIC_ERROR in str(excinfo.value.detail)

    attempts = await _attempts(session, 333)
    assert len(attempts) == 1
    assert attempts[0].success is False
    assert attempts[0].reason == "INVALIDO"
    assert attempts[0].attempted_code_hash is not None


async def test_confirm_codigo_vencido_404_generico(client, session):
    """Codigo vencido: 404 generico, motivo VENCIDO."""
    reg = await _register_ok(client, _unique_email())
    user = await _user(session, reg["user"]["id"])
    created = await telegram_link_service.create_link_code(session, user)

    account = await _account(session, user.id)
    assert account is not None
    account.link_expires_at = _utcnow() - timedelta(minutes=1)
    await session.commit()

    with pytest.raises(HTTPException) as excinfo:
        await telegram_link_service.confirm_link(
            session, created.code, telegram_user_id=444, chat_id=444
        )
    assert excinfo.value.status_code == 404
    assert _GENERIC_ERROR in str(excinfo.value.detail)

    attempts = await _attempts(session, 444)
    assert len(attempts) == 1
    assert attempts[0].success is False
    assert attempts[0].reason == "VENCIDO"


async def test_confirm_codigo_de_un_solo_uso(client, session):
    """El mismo codigo no vincula dos veces."""
    reg = await _register_ok(client, _unique_email())
    user = await _user(session, reg["user"]["id"])
    created = await telegram_link_service.create_link_code(session, user)

    await telegram_link_service.confirm_link(
        session, created.code, telegram_user_id=555, chat_id=555
    )
    with pytest.raises(HTTPException) as excinfo:
        await telegram_link_service.confirm_link(
            session, created.code, telegram_user_id=556, chat_id=556
        )
    assert excinfo.value.status_code == 404
    assert _GENERIC_ERROR in str(excinfo.value.detail)


async def test_confirm_limite_por_chat(client, session):
    """5 fallos en 15 minutos bloquean el chat (6o intento LIMITADO)."""
    reg = await _register_ok(client, _unique_email())
    user = await _user(session, reg["user"]["id"])
    await telegram_link_service.create_link_code(session, user)

    for _ in range(5):
        with pytest.raises(HTTPException) as excinfo:
            await telegram_link_service.confirm_link(
                session, "ZZZZZZZZZZ", telegram_user_id=666, chat_id=666
            )
        assert excinfo.value.status_code == 404

    # El sexto intento (incluso con el codigo correcto) se bloquea.
    created = await telegram_link_service.create_link_code(session, user)
    with pytest.raises(HTTPException) as excinfo:
        await telegram_link_service.confirm_link(
            session, created.code, telegram_user_id=666, chat_id=666
        )
    assert excinfo.value.status_code == 404
    assert _GENERIC_ERROR in str(excinfo.value.detail)

    attempts = await _attempts(session, 666)
    assert len(attempts) == 6
    assert attempts[-1].success is False
    assert attempts[-1].reason == "LIMITADO"
    # El codigo correcto no se vinculo por el bloqueo.
    account = await _account(session, user.id)
    assert account is not None
    assert account.status == "PENDIENTE"


async def test_confirm_minusculas_funciona(client, session):
    """El codigo en minusculas tambien vincula (normalizacion)."""
    reg = await _register_ok(client, _unique_email())
    user = await _user(session, reg["user"]["id"])
    created = await telegram_link_service.create_link_code(session, user)

    account = await telegram_link_service.confirm_link(
        session, created.code.lower(), telegram_user_id=777, chat_id=777
    )
    assert account.status == "VINCULADA"


# ------------------------------------------------------------------
# POST /telegram/unlink
# ------------------------------------------------------------------


async def test_unlink_revoca_y_permite_revincular(client, session):
    """Desvincular pasa a REVOCADA; un codigo nuevo revive el vinculo."""
    reg = await _register_ok(client, _unique_email())
    token = reg["access_token"]
    user = await _user(session, reg["user"]["id"])
    created = await telegram_link_service.create_link_code(session, user)
    await telegram_link_service.confirm_link(
        session, created.code, telegram_user_id=888, chat_id=888
    )

    response = await client.post("/api/v1/telegram/unlink", headers=_headers(token))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "REVOCADA"
    assert response.json()["has_pending_code"] is False

    account = await _account(session, user.id)
    assert account is not None
    assert account.status == "REVOCADA"
    assert account.link_code_hash is None
    assert account.link_expires_at is None

    # Revincular con un codigo nuevo funciona (otro chat).
    created2 = await telegram_link_service.create_link_code(session, user)
    account2 = await telegram_link_service.confirm_link(
        session, created2.code, telegram_user_id=889, chat_id=889
    )
    assert account2.status == "VINCULADA"
    assert account2.chat_id == 889


async def test_unlink_sin_cuenta_200_sin_vincular(client):
    """Desvincular sin cuenta devuelve SIN_VINCULAR (200)."""
    reg = await _register_ok(client, _unique_email())
    token = reg["access_token"]
    response = await client.post("/api/v1/telegram/unlink", headers=_headers(token))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "SIN_VINCULAR"
