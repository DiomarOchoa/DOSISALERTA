"""Fixtures compartidas de las pruebas de autenticacion (Fase 3)."""

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _jwt_test_env(monkeypatch):
    """Fija las variables JWT de prueba para cada test.

    Ambito de funcion (el valor por defecto): es el unico compatible
    con monkeypatch, que es una fixture de ambito de funcion. Una
    fixture de sesion que intentara usar monkeypatch fallaria con
    ScopeMismatch. Al ser autouse, corre antes de cada test —incluidos
    los 43 existentes— sin modificarlos.
    """
    monkeypatch.setenv("JWT_SECRET", "test-secret-de-al-menos-32-caracteres-0123456789")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_ACCESS_EXPIRATION_MINUTES", "60")
    monkeypatch.setenv("JWT_REFRESH_EXPIRATION_DAYS", "7")
    # get_settings() esta cacheada con lru_cache. Sin limpiar la caché,
    # create_app() (que llama a get_settings()) usaría un Settings
    # construido con las variables de un test anterior.
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
