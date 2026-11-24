"""Pruebas de soporte de DATABASE_URL en la configuracion.

Cubre la correccion de conexion de Render (2026-11-23): el backend
antes ignoraba DATABASE_URL y conectaba a localhost:5432 por defecto.

Independencia entre pruebas (igual que test_config.py):

- Se usa ``Settings()`` directamente, NUNCA ``get_settings()``.
- Cada prueba fija o borra sus variables con ``monkeypatch``, que las
  restaura automaticamente al terminar.
- Antes de cada prueba se borran `DATABASE_URL`, `ALEMBIC_DATABASE_URL`
  y las cinco variables `POSTGRES_*`, para que el entorno donde se
  ejecuta Pytest (incluido el `.env` del proyecto, cargado al importar
  la configuracion) no influya en el resultado. `ALEMBIC_DATABASE_URL`
  se borra tambien porque las fixtures de sesion de otros modulos la
  dejan puesta en `os.environ` hasta el final de la sesion.
- Los secretos obligatorios (JWT, cuidadores, Telegram) se fijan con
  valores de prueba, para que `Settings()` no dependa del `.env`.

Ninguna prueba se conecta a una base de datos real: solo se construye
y se valida la URL. Se ejecutan desde la carpeta ``backend/`` con::

    pytest app/tests/test_database_url.py
"""

from pathlib import Path

import pytest

from app.core.config import Settings, normalize_database_url

BACKEND_DIR = Path(__file__).resolve().parents[2]

_DB_VARS = (
    "DATABASE_URL",
    "ALEMBIC_DATABASE_URL",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)


def _clean_db_env(monkeypatch):
    """Borra las variables de conexion y fija los secretos de prueba."""
    for name in _DB_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "JWT_SECRET", "test-secret-de-al-menos-32-caracteres-0123456789"
    )
    monkeypatch.setenv(
        "CAREGIVER_LINK_SECRET",
        "test-caregiver-secret-de-32-o-mas-0123456789",
    )
    monkeypatch.setenv(
        "TELEGRAM_LINK_SECRET",
        "test-telegram-secret-de-32-o-mas-0123456789",
    )


def test_postgres_scheme_is_normalized(monkeypatch):
    """postgres:// pasa a postgresql+asyncpg://, resto intacto."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://qa_user:qa_pass@db.internal:5432/dosisalerta",
    )
    assert Settings().database_url == (
        "postgresql+asyncpg://qa_user:qa_pass@db.internal:5432/dosisalerta"
    )


def test_postgresql_scheme_is_normalized(monkeypatch):
    """postgresql:// pasa a postgresql+asyncpg://, resto intacto."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://qa_user:qa_pass@db.internal:5432/dosisalerta",
    )
    assert Settings().database_url == (
        "postgresql+asyncpg://qa_user:qa_pass@db.internal:5432/dosisalerta"
    )


def test_asyncpg_scheme_is_kept(monkeypatch):
    """postgresql+asyncpg:// se usa tal cual, sin cambios."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://qa_user:qa_pass@db.internal:5432/dosisalerta",
    )
    assert Settings().database_url == (
        "postgresql+asyncpg://qa_user:qa_pass@db.internal:5432/dosisalerta"
    )


def test_encoded_credentials_are_preserved(monkeypatch):
    """Credenciales ya codificadas en la URL se conservan tal cual."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://qa_user:p%40ss%3Aw%25rd@db.internal:5432/dosisalerta",
    )
    assert Settings().database_url == (
        "postgresql+asyncpg://qa_user:p%40ss%3Aw%25rd"
        "@db.internal:5432/dosisalerta"
    )


def test_special_characters_are_quoted_when_built_from_pieces(monkeypatch):
    """Al construir desde las piezas, usuario y contrasena se codifican."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "dosisalerta")
    monkeypatch.setenv("POSTGRES_USER", "qa_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:w/rd%")
    assert Settings().database_url == (
        "postgresql+asyncpg://qa_user:p%40ss%3Aw%2Frd%25"
        "@db.internal:5433/dosisalerta"
    )


def test_query_params_are_preserved(monkeypatch):
    """Los parametros de la URL (por ejemplo sslmode) se conservan."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://qa_user:qa_pass@db.internal:5432/dosisalerta"
        "?sslmode=require&connect_timeout=10",
    )
    assert Settings().database_url == (
        "postgresql+asyncpg://qa_user:qa_pass@db.internal:5432/dosisalerta"
        "?sslmode=require&connect_timeout=10"
    )


def test_fallback_to_postgres_pieces(monkeypatch):
    """Sin DATABASE_URL se usan las cinco piezas, como hasta ahora."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "mi_db")
    monkeypatch.setenv("POSTGRES_USER", "mi_usuario")
    monkeypatch.setenv("POSTGRES_PASSWORD", "clave")
    assert Settings().database_url == (
        "postgresql+asyncpg://mi_usuario:clave@db.internal:5433/mi_db"
    )


def test_no_config_uses_piecewise_defaults(monkeypatch):
    """Sin ninguna variable de conexion se usan los defectos historicos.

    Las cinco piezas siempre tienen defecto (localhost:5432), asi que
    la ausencia total de configuracion construye la URL local, no un
    error: es el comportamiento de desarrollo local, que la suite y
    docker-compose usan. El error claro existe para el caso peligroso:
    DATABASE_URL definida pero no valida (ver los dos tests siguientes).
    """
    _clean_db_env(monkeypatch)
    assert Settings().database_url == (
        "postgresql+asyncpg://dosisalerta:dosisalerta@localhost:5432/dosisalerta"
    )


def test_database_url_wins_over_pieces(monkeypatch):
    """Con ambas configuraciones, DATABASE_URL tiene prioridad."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://qa_user:qa_pass@db.render:5432/dosisalerta",
    )
    monkeypatch.setenv("POSTGRES_HOST", "otro.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "otra_db")
    monkeypatch.setenv("POSTGRES_USER", "otro_usuario")
    monkeypatch.setenv("POSTGRES_PASSWORD", "otra_clave")
    assert Settings().database_url == (
        "postgresql+asyncpg://qa_user:qa_pass@db.render:5432/dosisalerta"
    )


def test_empty_database_url_falls_back_to_pieces(monkeypatch):
    """DATABASE_URL vacia o en blanco se trata como ausente."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "   ")
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "dosisalerta")
    monkeypatch.setenv("POSTGRES_USER", "qa_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "clave")
    assert Settings().database_url == (
        "postgresql+asyncpg://qa_user:clave@db.internal:5433/dosisalerta"
    )


def test_invalid_scheme_raises_clear_error_without_credentials(monkeypatch):
    """Esquema no admitido: error claro, sin filtrar credenciales."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql://qa_user:Secreto123@db.internal:5432/dosisalerta",
    )
    with pytest.raises(ValueError) as excinfo:
        Settings()
    message = str(excinfo.value)
    assert "DATABASE_URL" in message
    assert "Secreto123" not in message
    assert "qa_user" not in message


def test_url_without_host_raises_clear_error_without_credentials(monkeypatch):
    """URL sin host: error claro, sin filtrar credenciales."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://qa_user:Secreto123@/dosisalerta",
    )
    with pytest.raises(ValueError) as excinfo:
        Settings()
    message = str(excinfo.value)
    assert "DATABASE_URL" in message
    assert "Secreto123" not in message
    assert "qa_user" not in message


def test_repr_hides_database_url_password(monkeypatch):
    """repr(Settings) no muestra la contrasena de DATABASE_URL."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://qa_user:Secreto123@db.internal:5432/dosisalerta",
    )
    assert "Secreto123" not in repr(Settings())


def test_repr_hides_piecewise_password(monkeypatch):
    """repr(Settings) no muestra la contrasena de las piezas."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv("POSTGRES_PASSWORD", "Secreto123")
    assert "Secreto123" not in repr(Settings())


def test_normalize_database_url_is_the_single_source(monkeypatch):
    """La normalizacion vive en una sola funcion, reutilizable."""
    assert normalize_database_url(
        "postgres://u:p@h:5432/db"
    ) == "postgresql+asyncpg://u:p@h:5432/db"
    assert normalize_database_url(
        "postgresql://u:p@h:5432/db"
    ) == "postgresql+asyncpg://u:p@h:5432/db"
    assert normalize_database_url(
        "postgresql+asyncpg://u:p@h:5432/db"
    ) == "postgresql+asyncpg://u:p@h:5432/db"


def _load_alembic_env(monkeypatch):
    """Carga backend/alembic/env.py con el contexto de Alembic simulado.

    Importar env.py ejecuta el corredor de migraciones en el nivel del
    modulo; con el contexto simulado esa ejecucion es un no-op y solo
    queda disponible `_database_url()` para probarla. Los parches se
    hacen con monkeypatch, que los restaura al terminar el test, para
    no contaminar los tests de migraciones reales del resto de la suite.
    """
    import importlib.util
    from unittest import mock

    from alembic import context

    # `config` no existe como atributo del modulo fuera de una migracion
    # real: se crea con raising=False y monkeypatch lo retira al final.
    monkeypatch.setattr(context, "config", mock.Mock(), raising=False)
    context.config.config_file_name = None
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    monkeypatch.setattr(context, "configure", mock.Mock())
    monkeypatch.setattr(context, "begin_transaction", mock.MagicMock())
    monkeypatch.setattr(context, "run_migrations", mock.Mock())
    spec = importlib.util.spec_from_file_location(
        "dosisalerta_alembic_env", BACKEND_DIR / "alembic" / "env.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alembic_uses_central_config(monkeypatch):
    """Alembic usa la misma configuracion central (DATABASE_URL)."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://qa_user:qa_pass@db.internal:5432/dosisalerta",
    )
    env = _load_alembic_env(monkeypatch)
    assert env._database_url() == (
        "postgresql+asyncpg://qa_user:qa_pass@db.internal:5432/dosisalerta"
    )


def test_alembic_override_is_normalized(monkeypatch):
    """ALEMBIC_DATABASE_URL sigue ganando y tambien se normaliza."""
    _clean_db_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://qa_user:qa_pass@db.internal:5432/dosisalerta",
    )
    monkeypatch.setenv(
        "ALEMBIC_DATABASE_URL",
        "postgres://qa_user:qa_pass@db.internal:5432/dosisalerta_test",
    )
    env = _load_alembic_env(monkeypatch)
    assert env._database_url() == (
        "postgresql+asyncpg://qa_user:qa_pass@db.internal:5432/dosisalerta_test"
    )
