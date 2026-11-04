# Backend — DosisAlerta (Python + FastAPI)

> Estado: **Fase 1 — implementada, pendiente de revisión.**
> Ya existe `pyproject.toml`, `app/main.py`, la configuracion central
> y el endpoint de salud con su prueba. Todavia NO hay modelos,
> migraciones, autenticacion, medicamentos ni recordatorios: eso
> llega en las fases 2 a 6. No se ha hecho ningun commit.
>
> Correccion importante de la Fase 0: un borrador anterior,
> interrumpido, usaba un stack distinto al exigido por la asignatura.
> Ese stack **no cumple** el requisito oficial (aplicacion real en
> Python) y por eso se descarto por completo. El backend principal es
> Python, sin excepcion, y en esta documentacion no se mantiene
> ninguna segunda arquitectura.

## Lo que ya existe (Fase 1)

```text
backend/
├── pyproject.toml        # Dependencias. NO requirements.txt duplicado.
└── app/
    ├── main.py           # FastAPI + CORS + routers de salud
    ├── core/
    │   └── config.py     # Configuracion central desde .env
    ├── config/           # Reservado: ajustes por entorno (futuro)
    ├── database/         # Reservado: sesion async SQLAlchemy (Fase 2)
    ├── models/           # Reservado: tablas SQLAlchemy (Fase 2)
    ├── schemas/          # Reservado: esquemas Pydantic (Fase 3+)
    ├── repositories/     # Reservado: solo consultas a BD (Fase 2)
    ├── services/         # Reservado: logica de negocio (Fase 4+)
    ├── api/
    │   └── routers/
    │       └── health.py # GET /health y GET /api/v1/health
    ├── bot/              # Reservado: python-telegram-bot (Fase 6)
    ├── scheduler/        # Reservado: motor de recordatorios (Fase 5)
    ├── algorithms/       # Reservado: cola de prioridad (Fase 5)
    ├── utils/            # Reservado: tiempo, zonas horarias, formato
    └── tests/
        └── test_health.py # Pytest: /health 200, /api/v1/health, 404
```

Los paquetes reservados solo tienen un `__init__.py` con un
docstring que dice para que fase son. No contienen codigo fingido:
la estructura esta lista para crecer sin reorganizar carpetas, pero
nada aparenta funcionar antes de su fase.

## Endpoints de la Fase 1

| Metodo y ruta | Respuesta | Para que sirve |
|---|---|---|
| `GET /health` | `{"status": "ok", "app": "DosisAlerta", "version": "0.1.0"}` | Comprobacion canonica de que el proceso vive |
| `GET /api/v1/health` | La misma respuesta | Que el frontend, que trabaja contra `/api/v1`, no tenga que salirse de su URL base |

La documentacion OpenAPI se genera sola en `/docs` (Swagger UI) y
en `/openapi.json`. Ningun endpoint de la Fase 1 toca la base de
datos: el backend arranca y responde `/health` sin PostgreSQL.

## Dos procesos, un mismo codigo y una misma base de datos

```text
Proceso API  (uvicorn app.main:app)   → REST + scheduler (envia avisos, Fase 5)
Proceso BOT  (python -m app.bot.main) → polling de Telegram (Fase 6)
Ambos importan los mismos services/ y models/. Ninguno tiene su propia BD.
```

En la Fase 1 solo existe el proceso API. El proceso BOT y el
scheduler (que vivira en el lifespan de la API) llegan en las
Fases 5 y 6.

## Ejecucion (Fase 1)

### Windows PowerShell

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

### Linux / macOS

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

- API en http://localhost:8000 — documentacion en
  http://localhost:8000/docs
- Comprobacion rapida: `curl http://localhost:8000/health`
- Pruebas: `pytest` (desde `backend/`, con el entorno activado).
  En la Fase 1 son 3 pruebas y no necesitan Docker ni PostgreSQL.
- **No ejecutar `alembic` todavia:** no hay migraciones hasta la
  Fase 2. Si se ejecuta ahora, fallara porque no existe el paquete
  `alembic` ni el directorio de migraciones, y eso es lo esperado.

## Configuracion

Toda la configuracion vive en `app/core/config.py` y sale de
variables de entorno (archivo `.env` en la raiz, copiado desde
`.env.example`, en desarrollo). No hay credenciales reales en el
codigo y `database_url` nunca se imprime en logs, porque contiene
la contrasena. En la Fase 1 solo se usan: nombre de la app, puerto
y origenes CORS (por defecto, solo `http://localhost:5173`). Las
variables de PostgreSQL se guardan ya en la configuracion para la
Fase 2, pero no se abre ninguna conexion todavia. JWT y token de
Telegram no se leen todavia: se anaden en sus fases.

## Versiones verificadas en la Fase 1

Probadas en el entorno de desarrollo de la Fase 1 (Python 3.12.3):

| Dependencia | Version instalada |
|---|---|
| FastAPI | 0.162.0 |
| Uvicorn | 0.54.0 |
| Pydantic | 2.14.2 |
| python-dotenv | 1.2.4 |
| tzdata | 2026.6 |
| Pytest | 9.2.0 |
| HTTPX | 0.28.1 |

Observacion sin ocultar: con esta combinacion de versiones, Pytest
muestra una advertencia de deprecacion de Starlette sobre
`TestClient` (sugiere `httpx2` en el futuro). Las 3 pruebas pasan
igual; no se cambio la dependencia para no introducir una libreria
no verificada en la Fase 1.

## Reglas que ya estan decididas

- Un solo backend Python y una sola base de datos para la web y Telegram.
- Telegram nunca accede directamente a PostgreSQL: solo llama a servicios.
- Todo el backend es async (SQLAlchemy async + asyncpg) a partir de
  la Fase 2. No se mezclan sesiones sync y async en los servicios.
- API versionada: `/api/v1/...`. Documentacion automatica en `/docs`
  (Swagger UI) y `/openapi.json`, generadas por FastAPI.
- Contraseñas con bcrypt; JWT con secreto solo por variable de entorno.
- El historial nunca se borra con DELETE: se cancela o desactiva y se conserva.
