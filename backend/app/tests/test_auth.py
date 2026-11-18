"""Pruebas de integracion de autenticacion (Fase 3).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 2. La base de desarrollo (`dosisalerta`) no recibe
filas de prueba: cada prueba corre dentro de una transaccion que
se revierte al final (con `join_transaction_mode="create_savepoint"`,
porque los servicios hacen `commit` y sin savepoint el commit
confirmaria la transaccion exterior).

Las llamadas HTTP usan `httpx.AsyncClient` + `ASGITransport`
(en el mismo bucle de eventos que la prueba), para que la sesion
de la prueba —ligada a ese bucle— funcione dentro de cada peticion.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import httpx
import jwt
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import security
from app.core.config import get_settings
from app.database import get_session
from app.main import create_app
from app.models import RefreshToken, User
from app.repositories import refresh_token_repository

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

    `join_transaction_mode="create_savepoint"`: la sesion se une a
    la transaccion exterior mediante un savepoint, asi que los
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


async def _register(client, email, password=PASSWORD, name="Prueba", timezone="America/Bogota"):
    return await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": password, "timezone": timezone},
    )


async def _register_ok(client, email, password=PASSWORD):
    response = await _register(client, email, password=password)
    assert response.status_code == 201, response.text
    return response.json()


async def _login(client, email, password=PASSWORD):
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


async def _make_user(session, email, password=PASSWORD, is_active=True):
    user = User(
        name="Prueba",
        email=email,
        password_hash=security.hash_password(password),
        timezone="America/Bogota",
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_refresh_token(session, user_id, raw=None, expires_at=None, revoked_at=None):
    raw = raw or security.generate_refresh_token()
    token = RefreshToken(
        user_id=user_id,
        token_hash=security.hash_refresh_token(raw),
        expires_at=expires_at
        or (datetime.now(timezone.utc) + timedelta(days=7)),
        revoked_at=revoked_at,
    )
    session.add(token)
    await session.flush()
    return raw, token


async def _count_refresh_tokens(session, user_id, only_active=False):
    stmt = select(RefreshToken).where(RefreshToken.user_id == user_id)
    if only_active:
        stmt = stmt.where(RefreshToken.revoked_at.is_(None))
    result = await session.execute(stmt)
    return len(result.scalars().all())


async def _committed_user_with_token(test_engine, email):
    """Crea usuario + refresh token con commit (visible para otras conexiones).

    Devuelve (user_id, refresh_token_en_claro). Para las pruebas de
    concurrencia, que necesitan datos confirmados y sesiones propias.
    """
    raw = security.generate_refresh_token()
    async with AsyncSession(test_engine, expire_on_commit=False) as setup:
        user = User(
            name="Prueba",
            email=email,
            password_hash=security.hash_password(PASSWORD),
        )
        setup.add(user)
        await setup.flush()
        user_id = user.id
        setup.add(
            RefreshToken(
                user_id=user.id,
                token_hash=security.hash_refresh_token(raw),
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
        )
        await setup.commit()
    return user_id, raw


async def _delete_user_and_tokens(test_engine, user_id):
    """Borra un usuario y sus tokens (limpieza tras pruebas con commit)."""
    async with AsyncSession(test_engine, expire_on_commit=False) as cleanup:
        await cleanup.execute(
            text("DELETE FROM refresh_tokens WHERE user_id = :uid"),
            {"uid": user_id},
        )
        await cleanup.execute(
            text("DELETE FROM users WHERE id = :uid"), {"uid": user_id}
        )
        await cleanup.commit()


# ------------------------------------------------------------------
# 1. Registro (11 pruebas)
# ------------------------------------------------------------------


async def test_register_valid(client):
    """Registro valido -> 201, usuario (sin password_hash) + tokens."""
    email = _unique_email()
    response = await _register(client, email)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == email
    assert body["user"]["name"] == "Prueba"
    assert body["user"]["timezone"] == "America/Bogota"
    assert body["user"]["is_active"] is True
    assert isinstance(body["user"]["id"], int)
    assert "password_hash" not in body["user"]
    assert "password_hash" not in response.text
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_register_duplicate_email(client):
    """Email duplicado -> 409."""
    email = _unique_email()
    first = await _register(client, email)
    assert first.status_code == 201
    second = await _register(client, email)
    assert second.status_code == 409
    assert second.json()["detail"] == "El correo ya está registrado"


async def test_register_invalid_email(client):
    """Email invalido -> 422."""
    response = await _register(client, "no-es-un-email")
    assert response.status_code == 422


async def test_register_short_password(client):
    """Contrasena de menos de 8 caracteres -> 422."""
    response = await _register(client, _unique_email(), password="corta")
    assert response.status_code == 422


async def test_register_long_password(client):
    """Contrasena de mas de 72 bytes -> 422."""
    response = await _register(client, _unique_email(), password="x" * 100)
    assert response.status_code == 422


async def test_register_invalid_timezone(client):
    """Zona horaria invalida -> 422."""
    response = await _register(client, _unique_email(), timezone="No/Existe")
    assert response.status_code == 422


async def test_register_missing_name(client):
    """Nombre ausente -> 422."""
    email = _unique_email()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 422


async def test_register_password_hashed_in_db(client, session):
    """La contrasena queda hasheada en la BD (bcrypt, no en claro)."""
    email = _unique_email()
    response = await _register(client, email)
    assert response.status_code == 201
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    assert user.password_hash != PASSWORD
    assert user.password_hash.startswith("$2b$")
    assert security.verify_password(PASSWORD, user.password_hash) is True


async def test_register_user_active_and_timezone(client, session):
    """El usuario creado tiene is_active=True y la zona pedida."""
    email = _unique_email()
    response = await _register(client, email, timezone="America/Bogota")
    assert response.status_code == 201
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    assert user.is_active is True
    assert user.timezone == "America/Bogota"


async def test_register_atomic_happy_path(client, session):
    """Tras un registro valido, usuario Y exactamente un refresh token activo."""
    email = _unique_email()
    response = await _register(client, email)
    assert response.status_code == 201
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    assert await _count_refresh_tokens(session, user.id, only_active=True) == 1
    assert await _count_refresh_tokens(session, user.id) == 1


async def test_register_atomic_rollback(client, session, monkeypatch):
    """Si falla la creacion de la sesion, el usuario NO queda en la BD."""
    email = _unique_email()

    def _boom():
        raise RuntimeError("fallo forzado en la generacion del token")

    monkeypatch.setattr(security, "generate_refresh_token", _boom)
    response = await _register(client, email)
    assert response.status_code == 500
    result = await session.execute(select(User).where(User.email == email))
    assert result.scalar_one_or_none() is None


# ------------------------------------------------------------------
# 2. Login (7 pruebas)
# ------------------------------------------------------------------


async def test_login_valid(client):
    """Credenciales correctas -> 200, access + refresh + bearer."""
    email = _unique_email()
    await _register_ok(client, email)
    response = await _login(client, email)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert "password_hash" not in response.text


async def test_login_wrong_password(client):
    """Contrasena incorrecta -> 401 con el mensaje generico."""
    email = _unique_email()
    await _register_ok(client, email)
    response = await _login(client, email, password="clave-incorrecta-999")
    assert response.status_code == 401
    assert response.json()["detail"] == "Correo o contraseña incorrectos"


async def test_login_unknown_email(client):
    """Email inexistente -> 401 con el mismo mensaje (sin enumeracion)."""
    response = await _login(client, _unique_email("nadie"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Correo o contraseña incorrectos"


async def test_login_inactive_user(client, session):
    """Usuario inactivo -> 401."""
    email = _unique_email()
    await _make_user(session, email, is_active=False)
    response = await _login(client, email)
    assert response.status_code == 401
    assert response.json()["detail"] == "Correo o contraseña incorrectos"


async def test_login_long_password_422(client):
    """Contrasena de mas de 72 bytes -> 422, nunca 500."""
    email = _unique_email()
    await _register_ok(client, email)
    response = await _login(client, email, password="x" * 100)
    assert response.status_code == 422


async def test_login_access_token_is_valid_jwt(client):
    """El access token devuelto es un JWT valido con sub = id del usuario."""
    email = _unique_email()
    registered = await _register_ok(client, email)
    user_id = registered["user"]["id"]
    response = await _login(client, email)
    assert response.status_code == 200
    settings = get_settings()
    payload = jwt.decode(
        response.json()["access_token"],
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"


async def test_login_refresh_token_hash_stored(client, session):
    """El refresh token devuelto tiene su hash guardado en refresh_tokens."""
    email = _unique_email()
    registered = await _register_ok(client, email)
    user_id = registered["user"]["id"]
    response = await _login(client, email)
    assert response.status_code == 200
    raw = response.json()["refresh_token"]
    token_hash = security.hash_refresh_token(raw)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    token = result.scalar_one()
    assert token.user_id == user_id
    assert token.revoked_at is None


# ------------------------------------------------------------------
# 3. Renovacion (8 pruebas)
# ------------------------------------------------------------------


async def test_refresh_valid(client):
    """Refresh valido -> 200, nuevo access + nuevo refresh."""
    email = _unique_email()
    registered = await _register_ok(client, email)
    old_refresh = registered["refresh_token"]
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["refresh_token"] != old_refresh
    assert body["token_type"] == "bearer"


async def test_refresh_old_token_revoked(client, session):
    """El refresh anterior queda revocado tras la renovacion."""
    email = _unique_email()
    registered = await _register_ok(client, email)
    old_refresh = registered["refresh_token"]
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert response.status_code == 200
    token_hash = security.hash_refresh_token(old_refresh)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    token = result.scalar_one()
    assert token.revoked_at is not None


async def test_refresh_reuse_old_token_401(client):
    """Reutilizar el refresh anterior tras renovar -> 401."""
    email = _unique_email()
    registered = await _register_ok(client, email)
    old_refresh = registered["refresh_token"]
    first = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert second.status_code == 401


async def test_refresh_revoked_token_401(client, session):
    """Refresh token revocado -> 401."""
    email = _unique_email()
    user = await _make_user(session, email)
    raw, _ = await _make_refresh_token(
        session, user.id, revoked_at=datetime.now(timezone.utc)
    )
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": raw}
    )
    assert response.status_code == 401


async def test_refresh_expired_token_401(client, session):
    """Refresh token expirado -> 401."""
    email = _unique_email()
    user = await _make_user(session, email)
    raw, _ = await _make_refresh_token(
        session,
        user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": raw}
    )
    assert response.status_code == 401


async def test_refresh_unknown_token_401(client):
    """Refresh token que no existe en la BD -> 401."""
    raw = security.generate_refresh_token()
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": raw}
    )
    assert response.status_code == 401


async def test_refresh_concurrent_http(test_engine):
    """5 POST /refresh simultaneos: exactamente 1x200 y 4x401."""
    email = _unique_email("concurrente")
    user_id, raw = await _committed_user_with_token(test_engine, email)
    try:
        get_settings.cache_clear()
        app = create_app()

        async def override_get_session():
            async with AsyncSession(test_engine, expire_on_commit=False) as s:
                yield s

        app.dependency_overrides[get_session] = override_get_session
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            responses = await asyncio.gather(
                *[
                    ac.post("/api/v1/auth/refresh", json={"refresh_token": raw})
                    for _ in range(5)
                ]
            )
        statuses = sorted(r.status_code for r in responses)
        assert statuses == [200, 401, 401, 401, 401], statuses
    finally:
        await _delete_user_and_tokens(test_engine, user_id)


async def test_refresh_concurrent_repository(test_engine):
    """Dos claim_for_refresh concurrentes: exactamente uno reclama."""
    email = _unique_email("repo-concurrente")
    user_id, raw = await _committed_user_with_token(test_engine, email)
    token_hash = security.hash_refresh_token(raw)
    try:

        async def claim_once():
            async with AsyncSession(test_engine, expire_on_commit=False) as s:
                claimed = await refresh_token_repository.claim_for_refresh(
                    s, token_hash, datetime.now(timezone.utc)
                )
                await s.commit()
                return claimed is not None

        results = await asyncio.gather(claim_once(), claim_once())
        assert sorted(results) == [False, True]
    finally:
        await _delete_user_and_tokens(test_engine, user_id)


# ------------------------------------------------------------------
# 4. Cierre de sesion (4 pruebas)
# ------------------------------------------------------------------


async def test_logout_valid(client, session):
    """Logout con refresh valido -> 200 y el token queda revocado."""
    email = _unique_email()
    registered = await _register_ok(client, email)
    raw = registered["refresh_token"]
    response = await client.post("/api/v1/auth/logout", json={"refresh_token": raw})
    assert response.status_code == 200
    assert response.json()["detail"] == "Sesión cerrada"
    token_hash = security.hash_refresh_token(raw)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    token = result.scalar_one()
    assert token.revoked_at is not None


async def test_logout_then_refresh_401(client):
    """Tras el logout, POST /refresh con ese token -> 401."""
    email = _unique_email()
    registered = await _register_ok(client, email)
    raw = registered["refresh_token"]
    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": raw})
    assert logout.status_code == 200
    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
    assert refresh.status_code == 401


async def test_logout_invalid_token_200(client):
    """Logout con token invalido -> 200 (no revela si era valido)."""
    raw = security.generate_refresh_token()
    response = await client.post("/api/v1/auth/logout", json={"refresh_token": raw})
    assert response.status_code == 200
    assert response.json()["detail"] == "Sesión cerrada"


async def test_logout_access_token_still_valid(client):
    """El access token sigue valido tras el logout (§7.5): /me -> 200."""
    email = _unique_email()
    registered = await _register_ok(client, email)
    access = registered["access_token"]
    raw = registered["refresh_token"]
    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": raw})
    assert logout.status_code == 200
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == email


# ------------------------------------------------------------------
# 5. Sesion (5 pruebas)
# ------------------------------------------------------------------


async def test_me_valid(client):
    """Con access token valido -> 200, perfil sin password_hash."""
    email = _unique_email()
    registered = await _register_ok(client, email)
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {registered['access_token']}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == email
    assert body["id"] == registered["user"]["id"]
    assert "password_hash" not in body


async def test_me_no_token(client):
    """Sin token -> 401."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_me_invalid_token(client):
    """Con token invalido -> 401."""
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer token-invalido"}
    )
    assert response.status_code == 401


async def test_me_expired_token(client):
    """Con token expirado -> 401."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {
            "sub": "1",
            "email": "x@example.com",
            "type": "access",
            "iat": now - timedelta(minutes=120),
            "exp": now - timedelta(minutes=60),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401


async def test_me_deleted_user(client, session):
    """Con token de un usuario que ya no existe -> 401."""
    email = _unique_email()
    registered = await _register_ok(client, email)
    access = registered["access_token"]
    user_id = registered["user"]["id"]
    await session.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
    await session.execute(delete(User).where(User.id == user_id))
    await session.flush()
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert response.status_code == 401


# ------------------------------------------------------------------
# 6. Aislamiento (1 prueba)
# ------------------------------------------------------------------


async def test_two_users_independent_tokens(client):
    """Dos usuarios: ids distintos y tokens independientes."""
    first = await _register_ok(client, _unique_email("primero"))
    second = await _register_ok(client, _unique_email("segundo"))
    assert first["user"]["id"] != second["user"]["id"]
    assert first["refresh_token"] != second["refresh_token"]
    # Revocar el token del primero no afecta al del segundo.
    logout = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": first["refresh_token"]}
    )
    assert logout.status_code == 200
    refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert refresh.status_code == 200


# ------------------------------------------------------------------
# 7. Migracion UNIQUE (1 prueba)
# ------------------------------------------------------------------


async def test_refresh_token_hash_unique_constraint(session):
    """Dos filas con el mismo token_hash -> la segunda falla (UNIQUE)."""
    user = await _make_user(session, _unique_email("unique"))
    raw = security.generate_refresh_token()
    token_hash = security.hash_refresh_token(raw)
    first = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    session.add(first)
    await session.flush()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            second = RefreshToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            session.add(second)
            await session.flush()
