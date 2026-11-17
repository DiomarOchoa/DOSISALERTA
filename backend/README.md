# Backend — DosisAlerta (Python + FastAPI)

> Estado: **Fases 1 y 2 — aprobadas y publicadas en GitHub.**
> Ya existen `pyproject.toml`, `app/main.py`, la configuracion central,
> el endpoint de salud con su prueba, los modelos SQLAlchemy de las
> 13 tablas y la migración inicial Alembic `f2a17166bccd` aplicada.
> Todavia NO hay autenticacion, medicamentos ni recordatorios: eso
> llega en las fases 3 a 6. Commits en la rama `main`: `2bc7ec8`
> (implementación Fase 1, 2026-11-04), `77d0d5c` (auditoría Fase 1,
> 2026-11-04), `819c44b` (correcciones Fase 1, 2026-11-04),
> `e8d4f0e` (decisiones cuidadores, auditoría e IA, 2026-11-11) y
> `5f75de0` (Fase 2, 2026-11-11).
>
> Correccion importante de la Fase 0: un borrador anterior,
> interrumpido, usaba un stack distinto al exigido por la asignatura.
> Ese stack **no cumple** el requisito oficial (aplicacion real en
> Python) y por eso se descarto por completo. El backend principal es
> Python, sin excepcion, y en esta documentacion no se mantiene
> ninguna segunda arquitectura.

## Lo que ya existe (Fases 1 y 2)

```text
backend/
├── pyproject.toml        # Dependencias. NO requirements.txt duplicado.
└── app/
    ├── main.py           # FastAPI + CORS + routers de salud
    ├── core/
    │   └── config.py     # Configuracion central desde .env
    ├── config/           # Reservado: ajustes por entorno (futuro)
    ├── database/         # Sesion async SQLAlchemy (Fase 2)
    ├── models/           # Tablas SQLAlchemy, 13 tablas (Fase 2)
    ├── schemas/          # Reservado: esquemas Pydantic (Fase 3+)
    ├── repositories/     # Solo consultas a BD (Fase 2)
    ├── services/         # Reservado: logica de negocio (Fase 4+)
    ├── api/
    │   └── routers/
    │       └── health.py # GET /health y GET /api/v1/health
    ├── bot/              # Esqueleto de demostración local, sin publicar (Fase 6)
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

## Ejecucion (Fases 1 y 2)

### Windows PowerShell

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-lock.txt
pip install -e . --no-deps
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Linux / macOS

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
pip install -e . --no-deps
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

- API en http://localhost:8000 — documentacion en
  http://localhost:8000/docs
- Comprobacion rapida: `curl http://localhost:8000/health`
- Pruebas: `pytest` (desde `backend/`, con el entorno activado).
  Son 43 pruebas (12 de la Fase 1 y 31 de la Fase 2). Las de
  modelos necesitan PostgreSQL en marcha y usan la base de datos
  aislada `dosisalerta_test`, que la propia sesión de pruebas crea
  y migra; la base de desarrollo no recibe filas de prueba.
- Migraciones: `alembic upgrade head` aplica la migración inicial
  `f2a17166bccd` (13 tablas de la Fase 2). `alembic current` debe
  mostrar `f2a17166bccd (head)`. Nunca ejecutar
  `alembic downgrade` en desarrollo.

## Configuracion

Toda la configuracion vive en `app/core/config.py` y sale de
variables de entorno (archivo `.env` en la raiz, copiado desde
`.env.example`, en desarrollo). No hay credenciales reales en el
codigo y `database_url` nunca se imprime en logs, porque contiene
la contrasena. El backend usa 9 variables implementadas: `HOST`,
`PORT`, `DEBUG`, `CORS_ORIGINS` y las cinco `POSTGRES_*` (ver
`.env.example`). Desde la Fase 2 se abre conexion a PostgreSQL con
esas variables. JWT y token de Telegram son variables reservadas
para las Fases 3 y 6 y no se leen todavia: se anaden en sus fases.
Validacion de
puertos: `PORT` y `POSTGRES_PORT` deben ser enteros entre 1 y
65535; una variable vacia o ausente usa el defecto, y un valor
invalido hace fallar el arranque con un error que nombra la
variable, en lugar de arrancar en silencio en otro puerto (ver
`app/tests/test_config.py`).

## Versiones verificadas (Fases 1 y 2)

Versión canónica: Python 3.13.4 (fijada en la Fase A con
`.python-version` y `requires-python >=3.12,<3.14`). Probada en el
PC del equipo con las mismas versiones de dependencias:

| Dependencia | Version instalada |
|---|---|
| FastAPI | 0.162.0 |
| Uvicorn | 0.54.0 |
| Pydantic | 2.14.2 |
| python-dotenv | 1.2.4 |
| tzdata | 2026.6 |
| Pytest | 9.2.0 |
| HTTPX | 0.28.1 |

Desde la auditoría de cierre, esas versiones están fijadas con `==`
en `pyproject.toml`. La instalación reproducible usa además
`requirements-lock.txt` (36 dependencias fijadas, Fase A): `pip install -r
requirements-lock.txt` y luego `pip install -e . --no-deps`. No
hay `requirements.txt` aparte y el lock no se edita a mano: para
actualizar una versión hay que cambiarla en `pyproject.toml`,
reinstalar en un entorno limpio, volver a pasar `pytest` (43
pruebas) y regenerar el lock con `pip freeze` (procedimiento
completo en la cabecera del propio lock).

Observacion sin ocultar: con esta combinacion de versiones, Pytest
muestra una advertencia de deprecacion de Starlette sobre
`TestClient` (sugiere `httpx2` en el futuro). Las 43 pruebas pasan
igual; no se cambio la dependencia para no introducir una libreria
no verificada.

## Reglas que ya estan decididas

- Un solo backend Python y una sola base de datos para la web y Telegram.
- Telegram nunca accede directamente a PostgreSQL: solo llama a servicios.
- Todo el backend es async (SQLAlchemy async + asyncpg) a partir de
  la Fase 2. No se mezclan sesiones sync y async en los servicios.
- API versionada: `/api/v1/...`. Documentacion automatica en `/docs`
  (Swagger UI) y `/openapi.json`, generadas por FastAPI.
- Contraseñas con bcrypt; JWT con secreto solo por variable de entorno.
- El historial nunca se borra con DELETE: se cancela o desactiva y se conserva.
