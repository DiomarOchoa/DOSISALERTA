"""Pruebas de validacion de puertos en la configuracion (Fase 1).

Estas pruebas comprueban el comportamiento de ``_getint`` a traves
de ``Settings``, que es la unica forma en que la aplicacion lee
`PORT` y `POSTGRES_PORT`.

Independencia entre pruebas (importante):

- Se usa ``Settings()`` directamente, NUNCA ``get_settings()``.
  ``get_settings()`` esta cacheada con ``lru_cache``: la primera
  prueba que la llamara fijaria la configuracion para todas las
  demas y las pruebas se contaminarian entre si.
- Cada prueba fija o borra sus variables con ``monkeypatch`` de
  Pytest, que las restaura automaticamente al terminar. Asi, ninguna
  prueba deja variables puestas para la siguiente.
- Antes de cada prueba se borran `PORT` y `POSTGRES_PORT` (sin
  fallar si no existen), para que el entorno donde se ejecuta
  Pytest no influya en el resultado.

Se ejecutan desde la carpeta ``backend/`` con::

    pytest
"""

import pytest

from app.core.config import Settings


def _clean_env(monkeypatch):
    """Borra las variables de puerto, sin fallar si no existen."""
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)


def test_port_abc_fails_with_variable_name(monkeypatch):
    """PORT=abc debe fallar con un error que nombre a PORT."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("PORT", "abc")
    with pytest.raises(ValueError, match="PORT"):
        Settings()


def test_port_99999_fails_out_of_range(monkeypatch):
    """PORT=99999 debe fallar por estar fuera de 1-65535."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("PORT", "99999")
    with pytest.raises(ValueError, match="PORT"):
        Settings()


def test_port_minus_1_fails_out_of_range(monkeypatch):
    """PORT=-1 debe fallar por estar fuera de 1-65535."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("PORT", "-1")
    with pytest.raises(ValueError, match="PORT"):
        Settings()


def test_port_0_fails_out_of_range(monkeypatch):
    """PORT=0 debe fallar por estar fuera de 1-65535."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("PORT", "0")
    with pytest.raises(ValueError, match="PORT"):
        Settings()


def test_postgres_port_xyz_fails_with_variable_name(monkeypatch):
    """POSTGRES_PORT=xyz debe fallar nombrando a POSTGRES_PORT."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("POSTGRES_PORT", "xyz")
    with pytest.raises(ValueError, match="POSTGRES_PORT"):
        Settings()


def test_valid_ports_are_accepted(monkeypatch):
    """Valores validos, incluidos los limites, se aceptan tal cual."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    settings = Settings()
    assert settings.port == 8080
    assert settings.postgres_port == 5433


def test_port_boundaries_1_and_65535_are_valid(monkeypatch):
    """Los limites 1 y 65535 son validos, no deben fallar."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("PORT", "1")
    monkeypatch.setenv("POSTGRES_PORT", "65535")
    settings = Settings()
    assert settings.port == 1
    assert settings.postgres_port == 65535


def test_empty_variables_use_defaults(monkeypatch):
    """Variables vacias usan el defecto, igual que si no existieran."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("PORT", "")
    monkeypatch.setenv("POSTGRES_PORT", "")
    settings = Settings()
    assert settings.port == 8000
    assert settings.postgres_port == 5432


def test_missing_variables_use_defaults(monkeypatch):
    """Sin variables, se usan los defectos 8000 y 5432."""
    _clean_env(monkeypatch)
    settings = Settings()
    assert settings.port == 8000
    assert settings.postgres_port == 5432
