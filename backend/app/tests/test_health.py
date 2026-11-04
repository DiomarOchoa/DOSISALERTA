"""Pruebas del endpoint de salud (Fase 1).

Estas pruebas no levantan un servidor real ni tocan la base de datos:
usan ``TestClient`` de FastAPI, que llama a la aplicacion en el mismo
proceso. Por eso son rapidas y se pueden ejecutar en cualquier
maquina, con o sin Docker.

Se ejecutan desde la carpeta ``backend/`` con::

    pytest
"""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_health_returns_200_and_ok_status():
    """GET /health debe responder 200 con status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "DosisAlerta"
    # La version existe, aunque sea la de desarrollo sin instalar.
    assert isinstance(body["version"], str) and body["version"] != ""


def test_api_v1_health_returns_same_payload():
    """GET /api/v1/health debe devolver lo mismo que /health."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unknown_route_returns_404():
    """Una ruta inexistente no debe devolver un falso exito."""
    response = client.get("/esta-ruta-no-existe")
    assert response.status_code == 404
