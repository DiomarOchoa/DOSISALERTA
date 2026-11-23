# Backend — DosisAlerta (Python + FastAPI)

> Estado: **Fases 1–8 — completadas. Fase 9 en curso.**
> Existe el backend completo: autenticación JWT, medicamentos,
> tratamientos con horarios, motor de recordatorios, historial,
> estadísticas, cuidadores con permisos y bot de Telegram sobre
> servicios reales. Modelos SQLAlchemy de las **14 tablas** con
> Alembic en head `8033addb5499`. Suite: **546 pasadas + 1 fallo
> conocido preexistente** (ver `ESTADO_PROYECTO.md`). HEAD:
> `2daf352` (merge de la Fase 8, 2026-11-22).
>
> Correccion importante de la Fase 0: un borrador anterior,
> interrumpido, usaba un stack distinto al exigido por la asignatura.
> Ese stack **no cumple** el requisito oficial (aplicacion real en
> Python) y por eso se descarto por completo. El backend principal es
> Python, sin excepcion, y en esta documentacion no se mantiene
> ninguna segunda arquitectura.

## Lo que existe (Fases 1–8)

```text
backend/
├── pyproject.toml        # Dependencias. NO requirements.txt duplicado.
├── alembic/              # Migraciones (head: 8033addb5499, 14 tablas)
└── app/
    ├── main.py           # FastAPI + CORS + routers + lifespan (scheduler)
    ├── core/
    │   └── config.py     # Configuracion central desde .env (3 secretos)
    ├── config/           # Ajustes por entorno
    ├── database/         # Sesion async SQLAlchemy
    ├── models/           # Tablas SQLAlchemy, 14 tablas
    ├── schemas/          # Esquemas Pydantic de entrada y salida
    ├── repositories/     # Solo consultas a BD
    ├── services/         # Logica de negocio (auth, medicamentos,
    │                     # tratamientos, recordatorios, stats,
    │                     # cuidadores, telegram_link, intake)
    ├── api/
    │   └── routers/
    │       ├── health.py        # GET /health y GET /api/v1/health
    │       ├── auth.py          # Registro, login, refresh, logout, /me, PATCH /me
    │       ├── medications.py   # CRUD + deactivate/reactivate
    │       ├── treatments.py    # CRUD + estados + medicamentos anidados
    │       ├── reminders.py     # Historial, confirm, postpone
    │       ├── stats.py         # Cumplimiento
    │       ├── caregivers.py    # Invitar, aceptar, permisos, revocar, auditoría
    │       └── telegram_link.py # Vinculación Telegram (link/unlink/status)
    ├── bot/              # Bot real sobre servicios reales (Fase 6)
    ├── scheduler/        # Motor de recordatorios (Fase 5; apagado por defecto)
    ├── algorithms/       # Cola de prioridad del motor
    ├── utils/            # Tiempo, zonas horarias, formato
    └── tests/            # 546 pruebas (ver abajo)
```

## Endpoints (`/api/v1`, todos con JWT salvo registro/login)

| Metodo y ruta | Respuesta | Para que sirve |
|---|---|---|
| `GET /health` y `GET /api/v1/health` | `{"status": "ok", "app": "DosisAlerta", "version": "0.1.0"}` | Comprobacion canonica de que el proceso vive |
| `POST /api/v1/auth/register` | 201, usuario + tokens | Registro con bcrypt |
| `POST /api/v1/auth/login` | 200, access + refresh | Login JSON |
| `POST /api/v1/auth/refresh` | 200, tokens nuevos | Rotación atómica del refresh |
| `POST /api/v1/auth/logout` | 200 | Revoca el refresh (el access sigue válido hasta 60 min) |
| `GET /api/v1/auth/me` | 200, perfil | Perfil sin `password_hash` |
| `PATCH /api/v1/auth/me` | 200, perfil | Cambia la zona horaria; recalcula solo las `PENDIENTE` futuras |
| `GET/POST /api/v1/medications` | lista / 201 | Catálogo propio del usuario |
| `GET/PATCH /api/v1/medications/{id}` | 200 | Detalle y edición (sin tocar dosis prescritas desde el cuidador) |
| `POST /api/v1/medications/{id}/deactivate` y `/reactivate` | 200 | Desactivar cancela sus `PENDIENTE` futuras; el historial se conserva |
| `GET/POST /api/v1/treatments` | lista / 201 | Tratamientos con medicamentos anidados y horarios |
| `GET/PATCH /api/v1/treatments/{id}` | 200 | Detalle y edición parcial |
| `POST /api/v1/treatments/{id}/pause`, `/resume`, `/cancel`, `/complete` | 200 | Cambios de estado (cancelar/pausar cancela las `PENDIENTE` futuras con motivo) |
| `GET /api/v1/reminders/history` | `{items, total, limit, offset}` | Historial con los 8 estados, filtros y paginación |
| `POST /api/v1/reminders/{id}/confirm` | 200, intake | Confirmar una toma (idempotente; origen WEB o TELEGRAM) |
| `POST /api/v1/reminders/{id}/postpone` | 200, `{original, child}` | Posponer 15/30/60 min (máx. 3 por cadena) |
| `GET /api/v1/stats/compliance` | `{summary, groups}` | Cumplimiento con gracia de 30 min inclusiva; `group_by` day/week/month/medication |
| `POST /api/v1/caregivers/invite` | 201, código (una sola vez) | Invitación de un solo uso (10 caracteres, 15 min) |
| `POST /api/v1/caregivers/accept-code` | 200 | El cuidador presenta el código (queda INVITADO) |
| `GET /api/v1/caregivers` | `{as_patient, as_caregiver}` | Vínculos del usuario |
| `POST /api/v1/caregivers/{id}/accept` | 200 | El paciente acepta y fija los 8 permisos |
| `PATCH /api/v1/caregivers/{id}/permissions` | 200 | Cambia permisos (gestionar exige ver) |
| `POST /api/v1/caregivers/{id}/revoke` | 200 | Revocación inmediata |
| `GET /api/v1/caregivers/audit` | `{items, total, limit, offset}` | Quién hizo qué con los datos del paciente |
| `POST /api/v1/telegram/link` | 201, código (una sola vez) | Código de vinculación Telegram |
| `POST /api/v1/telegram/unlink` | 200 | Desvincula el chat |
| `GET /api/v1/telegram/status` | 200, estado | SIN_VINCULAR / PENDIENTE / VINCULADA / REVOCADA |

La documentacion OpenAPI se genera sola en `/docs` (Swagger UI) y
en `/openapi.json`. El cuidador accede con `?patient_id=<id>` en
medicamentos, tratamientos, historial y estadísticas, con vínculo
ACTIVO y el permiso concreto; sin él, 403 con `ACCESS_DENIED` en
auditoría. El cuidador nunca confirma ni pospone dosis.

## Dos procesos, un mismo codigo y una misma base de datos

```text
Proceso API  (uvicorn app.main:app)   → REST + scheduler (envia avisos, Fase 5)
Proceso BOT  (python -m app.bot.main) → polling de Telegram (Fase 6)
Ambos importan los mismos services/ y models/. Ninguno tiene su propia BD.
```

Los dos procesos existen desde las Fases 5 y 6. El proceso BOT
solo arranca con el token real de BotFather en `.env` (sin token,
`_sender_from_config()` devuelve None). El scheduler vive en el
lifespan de la API y está **apagado por defecto**
(`SCHEDULER_ENABLED=false`): sin token real no se envía ningún
aviso (verificado en la Etapa 7: 0 filas ENVIADA/ENVIANDO).

## Ejecucion

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
  Son **546 pruebas + 1 fallo conocido preexistente**
  (`test_config_ignora_un_env_ajeno_en_el_directorio_de_trabajo`:
  el marcador del token en `.env` se filtra al entorno del test).
  Las pruebas usan la base de datos aislada `dosisalerta_test`,
  que la propia sesión de pruebas crea y migra; la base de
  desarrollo no recibe filas de prueba. Tras cambiar código del
  backend, **hay que reiniciar uvicorn** (el proceso en marcha
  sirve el código con el que arrancó).
- Migraciones: `alembic upgrade head` aplica la cadena completa
  hasta `8033addb5499` (14 tablas). `alembic current` debe
  mostrar `8033addb5499 (head)`. Nunca ejecutar
  `alembic downgrade` en desarrollo (la reversibilidad de la
  migración 14 se verificó en la BD de pruebas, no en desarrollo).
- Bot (solo con token real): `python -m app.bot.main` desde
  `backend/`, con el entorno activado.

## Configuracion

Toda la configuracion vive en `app/core/config.py` y sale de
variables de entorno (archivo `.env` en la raiz, copiado desde
`.env.example`, en desarrollo). No hay credenciales reales en el
codigo y `database_url` nunca se imprime en logs, porque contiene
la contrasena. **Tres secretos son obligatorios y el backend no
arranca sin ellos** (cada uno de al menos 32 caracteres):
`JWT_SECRET` (Fase 3), `CAREGIVER_LINK_SECRET` (cuidadores) y
`TELEGRAM_LINK_SECRET` (Fase 6). `TELEGRAM_BOT_TOKEN` es el token
real de BotFather (pendiente: sin él, el bot no arranca y el
programador no envía avisos); `TELEGRAM_BOT_USERNAME` es el
nombre del bot. `SCHEDULER_ENABLED` es `false` por defecto.
Validacion de
puertos: `PORT` y `POSTGRES_PORT` deben ser enteros entre 1 y
65535; una variable vacia o ausente usa el defecto, y un valor
invalido hace fallar el arranque con un error que nombra la
variable, en lugar de arrancar en silencio en otro puerto (ver
`app/tests/test_config.py`).

## Versiones verificadas (actualizado 2026-11-22)

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
`requirements-lock.txt` (41 dependencias fijadas, verificado 2026-11-22): `pip install -r
requirements-lock.txt` y luego `pip install -e . --no-deps`. No
hay `requirements.txt` aparte y el lock no se edita a mano: para
actualizar una versión hay que cambiarla en `pyproject.toml`,
reinstalar en un entorno limpio, volver a pasar `pytest` (546
pruebas) y regenerar el lock con `pip freeze` (procedimiento
completo en la cabecera del propio lock).

Observacion sin ocultar: con esta combinacion de versiones, Pytest
muestra una advertencia de deprecacion de Starlette sobre
`TestClient` (sugiere `httpx2` en el futuro). Las 546 pruebas pasan
igual; no se cambio la dependencia para no introducir una libreria
no verificada. Dependencias añadidas después de la Fase 2:
PyJWT 2.15.1, bcrypt 5.0.0, email-validator 2.4.0 (Fase 3) y
python-telegram-bot 22.8 (Fase 6).

## Reglas que ya estan decididas

- Un solo backend Python y una sola base de datos para la web y Telegram.
- Telegram nunca accede directamente a PostgreSQL: solo llama a servicios.
- Todo el backend es async (SQLAlchemy async + asyncpg) a partir de
  la Fase 2. No se mezclan sesiones sync y async en los servicios.
- API versionada: `/api/v1/...`. Documentacion automatica en `/docs`
  (Swagger UI) y `/openapi.json`, generadas por FastAPI.
- Contraseñas con bcrypt; JWT con secreto solo por variable de entorno.
- El historial nunca se borra con DELETE: se cancela o desactiva y se conserva.
