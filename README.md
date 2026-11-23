# DOSISALERTA

> **Estado: Fases 1–8 — COMPLETADAS. Fase 9 (auditoría y entrega) —
> EN CURSO. Entrega: 25 de noviembre de 2026, 12:00 m.**
> Backend FastAPI completo (medicamentos, tratamientos, horarios,
> recordatorios, historial, estadísticas, cuidadores, Telegram),
> frontend React completo (12 rutas) y bot de Telegram sobre
> servicios reales. Base de datos PostgreSQL 17.11 con **14
> tablas** y Alembic en head `8033addb5499`. Suite backend:
> **546 pasadas + 1 fallo conocido preexistente** (ver §Pruebas).
> Commits en `main`, en https://github.com/DiomarOchoa/DOSISALERTA.
> HEAD: `2daf352` (merge de la Fase 8, 2026-11-22).
> Distinción honesta: la implementación está hecha y verificada
> ejecutándola de verdad (ver `ESTADO_PROYECTO.md` y los informes
> `INFORME_ETAPA*.md`); lo que falta está listado en
> "Limitaciones conocidas" y no se presenta como hecho. El bot
> nunca ha corrido como proceso persistente ni ha enviado un aviso
> real: el token de BotFather sigue pendiente (ver §Telegram).

## El problema

Muchas personas olvidan tomar sus medicamentos a la hora indicada,
sobre todo cuando el tratamiento tiene varios medicamentos, dosis
distintas y horarios que cambian según el día. El olvido no es un
problema de voluntad: es un problema de organización y de recordatorio
en el momento exacto.

## Público objetivo

Personas con tratamientos médicos continuos que necesitan organizar
qué tomar, cuándo tomarlo y comprobar que lo tomaron. También sirve
como herramienta de apoyo para quien acompaña a un familiar en su
tratamiento (el sistema, en esta versión, gestiona los tratamientos
del propio usuario; no gestiona pacientes de terceros).

**Límite importante:** DosisAlerta es una herramienta de organización
y seguimiento. **No diagnostica, no recomienda medicamentos, no cambia
dosis y no sustituye la indicación de un profesional de salud.** Si un
horario o una dosis cambia, lo cambia el usuario siguiendo la
indicación de su médico.

## La solución

Un ecosistema con dos canales conectados al mismo backend Python y a
la misma base de datos PostgreSQL:

1. **Aplicación web (React + Vite + TypeScript):** registro e inicio
   de sesión, medicamentos, tratamientos, dosis y horarios, calendario
   de tomas, próximos recordatorios, historial, estadísticas de
   cumplimiento y vinculación con Telegram.
2. **Bot de Telegram (python-telegram-bot):** vinculación de cuentas,
   registro y consulta de medicamentos, creación y modificación de
   tratamientos, próximos recordatorios, notificaciones automáticas,
   confirmación de tomas, posposición de recordatorios, historial y
   cancelación de tratamientos, con botones interactivos.

Lo que se hace en un canal se refleja en el otro, porque ambos usan
los mismos servicios y la misma base de datos. No hay una base de
datos para la web y otra para Telegram.

## Características (por fases)

- [x] Fase 1: entorno, backend FastAPI con `/health` y frontend React
      inicial (aprobada y publicada, commits `2bc7ec8`, `77d0d5c` y
      `819c44b`; PostgreSQL 17.11 verificado el 2026-11-11, ver
      `docs/ENTORNO_LOCAL.md`).
- [x] Fase 2: modelos y base de datos PostgreSQL (aprobada y
      publicada, commits `e8d4f0e` y `5f75de0`; migración inicial
      `f2a17166bccd`, 13 tablas entonces, 31 pruebas de modelos en verde).
- [x] Fase 3: autenticación JWT y seguridad por usuario
      (implementada, probada y publicada el 2026-11-18, commit
      `017538a`, fusionada en `main`; registro, login, refresh con
      rotación atómica, logout y `/me`; migración `6ea5249ec805` con
      UNIQUE en `refresh_tokens.token_hash`; 49 pruebas nuevas en
      verde; suite 92/92 entonces).
- [x] Fase 4: medicamentos, tratamientos, dosis y horarios
      (publicada en `main` en `b5c27e6`, 2026-11-20; 173 pruebas
      entonces; historial `CANCELADA` preservado y ventana de 72 h).
- [x] Fase 5: motor de recordatorios con cola de prioridad y
      prevención de duplicados (completada 2026-11-21; heap propio,
      reclamación atómica, reconciliador, top-up cada 6 h; suite
      341 pasadas entonces).
- [x] Fase 6: bot de Telegram completo, con los mismos servicios
      (completado 2026-11-22; vinculación por código, 7 comandos,
      29 callbacks, botones YA LO TOMÉ / RECORDARME DESPUÉS,
      migración 14 `8033addb5499`; suite 545 pasadas entonces).
- [x] Fase 7: historial y estadísticas de cumplimiento
      (plan de 1.615 líneas, decisiones D-1 a D-11 de Diomar;
      endpoints `/reminders/history` y `/stats/compliance` con
      agrupación día/semana/mes/medicamento; gracia de 30 min
      inclusiva; 122 pruebas formales).
- [x] Fase 8: aplicación web React completa (completada 2026-11-22;
      12 rutas: inicio, medicamentos, tratamientos, recordatorios,
      historial, estadísticas, perfil, cuidadores, calendario;
      confirmación y posposición desde la web; cuidadores con
      permisos; cambio de zona horaria; merge `2daf352`).
- [ ] Fase 9: pruebas, despliegue y documentación final
      (EN CURSO: Etapas 7–9 de verificación y auditoría).

## Tecnologías

| Capa | Tecnología | Versión / nota |
|---|---|---|
| Lenguaje backend | Python | 3.13.4, versión canónica (`requires-python >=3.12,<3.14`) (único backend) |
| API | FastAPI + Uvicorn | Documentación OpenAPI/Swagger automática |
| ORM y migraciones | SQLAlchemy 2.0 (async) + Alembic | Instalado en la Fase 2: SQLAlchemy 2.1.8, Alembic 1.20.1, asyncpg 0.32.0. |
| Validación | Pydantic v2 | Instalado en la Fase 1 (2.14.2). Esquemas de entrada y salida. |
| Configuración | python-dotenv | Instalado en la Fase 1 (1.2.4). Secretos solo en `.env`, nunca en el repo. |
| Base de datos | PostgreSQL | `postgres:17.11-alpine` en Docker (desarrollo). Verificado 17.11 el 2026-11-11; el contenedor publica en el puerto del host 5433 (el 5432 lo ocupa un PostgreSQL 18 nativo). |
| Bot | python-telegram-bot | Bot real sobre servicios reales (Fase 6): 7 comandos, 29 callbacks, 1 handler de texto; python-telegram-bot 22.8. Polling en desarrollo (ver decisiones). Sin token real todavía: nunca ha corrido como proceso persistente. |
| Autenticación | JWT (PyJWT) + bcrypt | Instalado en la Fase 3 (PyJWT 2.15.1, bcrypt 5.0.0, email-validator 2.4.0). Access 60 min, refresh 7 días con rotación atómica. |
| Pruebas | Pytest + HTTPX | Instalados en la Fase 1 (Pytest 9.2.0, HTTPX 0.28.1). En la Fase 2 se añadió pytest-asyncio 1.4.1.post1 para las 31 pruebas de modelos contra PostgreSQL real. |
| Frontend | React + Vite + TypeScript | CSS moderno, sin framework CSS pesado |
| Entorno | Docker y Docker Compose | Solo PostgreSQL, verificado el 2026-11-11 (ver `docs/ENTORNO_LOCAL.md`) |
| Control de versiones | Git y GitHub | Repositorio público, rama `main`, HEAD `2daf352`; 14 tablas, Alembic head `8033addb5499`; suite 546 pasadas + 1 fallo conocido |

Versiones canónicas (Fase A): Python 3.13.4, Node.js 24.12.0,
npm 11.6.2, PostgreSQL 17.11. Dependencias verificadas: FastAPI
0.162.0, Uvicorn 0.54.0, Pydantic 2.14.2, Pytest 9.2.0, React
19.3.1, Vite 6.4.5, TypeScript 5.9.3. Suite backend actual:
**546 pasadas + 1 fallo conocido preexistente** (ver
`ESTADO_PROYECTO.md`); build del frontend en verde (83 módulos).
Detalle completo en `backend/README.md`, `frontend/README.md` y
`docs/GUIA_INSTALACION_WINDOWS.md`.

La justificación de cada elección, y lo que se rechazó, está en
`docs/decisions/DECISIONES_TECNICAS.md`. No se añade ninguna
tecnología fuera de esta tabla sin justificarla en ese documento.

## Estructura del repositorio

```text
DosisAlerta/
├── backend/                  # Python + FastAPI (ver backend/README.md)
│   └── app/
│       ├── core/ config/ database/ models/ schemas/
│       ├── repositories/ services/ api/routers/
│       ├── bot/ scheduler/ algorithms/ utils/ tests/
├── frontend/                 # React + Vite + TypeScript (ver frontend/README.md)
│   └── src/
│       ├── components/ pages/ services/ hooks/ context/ styles/
├── docs/
│   ├── architecture/         # ARQUITECTURA, REQUISITOS, ROADMAP
│   ├── database/             # MODELO_DATOS
│   ├── diagrams/             # DIAGRAMAS (Mermaid)
│   ├── decisions/            # DECISIONES_TECNICAS
│   └── presentation/         # Material de sustentación (Fase 9)
├── docker/                   # Reservado para despliegue (Fase 9)
├── .env.example              # Plantilla SIN credenciales reales
├── .gitignore
├── docker-compose.yml        # Solo PostgreSQL en la Fase 0
├── README.md
└── ESTADO_PROYECTO.md
```

## Requisitos previos

- Python 3.13.4 (versión canónica).
- Node.js 24.12.0 y npm 11.6.2 (versiones canónicas).
- Docker y Docker Compose (para PostgreSQL local).
- Git.
- Una cuenta de GitHub propia (para contribuir; ver
  `docs/GUIA_INSTALACION_WINDOWS.md`, paso 20).

> Telegram no es un requisito previo para instalar el entorno
> común, pero el backend **no arranca** sin los tres secretos de
> `.env` (`JWT_SECRET`, `CAREGIVER_LINK_SECRET`,
> `TELEGRAM_LINK_SECRET`, cada uno de al menos 32 caracteres;
> ver `.env.example`). El token real de BotFather
> (`TELEGRAM_BOT_TOKEN`) sigue pendiente: sin él el bot no
> arranca y el programador no envía avisos.

## Instalación y ejecución (verificadas)

> Backend y frontend se probaron de verdad en cada fase (ver
> `ESTADO_PROYECTO.md`). PostgreSQL se verificó el 2026-11-11 en
> el PC del equipo (17.11, `pg_isready` con "accepting
> connections", ver `docs/ENTORNO_LOCAL.md`).
> Las migraciones existen desde la Fase 2 (`alembic upgrade head`
> crea las 14 tablas; head actual `8033addb5499`); nunca usar
> `create_all` como mecanismo de evolución del esquema y nunca
> ejecutar `alembic downgrade` en desarrollo.

### Windows PowerShell

```powershell
# 1. Variables de entorno (nunca subir .env a Git)
Copy-Item .env.example .env
# Editar .env: contraseña de PostgreSQL y POSTGRES_PORT según el
# paso 8 de docs/GUIA_INSTALACION_WINDOWS.md (detectar puertos
# primero). Generar los tres secretos (JWT_SECRET,
# CAREGIVER_LINK_SECRET, TELEGRAM_LINK_SECRET, >=32 caracteres
# cada uno; ver .env.example). Sin ellos el backend no arranca.
# TELEGRAM_BOT_TOKEN queda pendiente hasta tener el token real
# de BotFather (ver docs/bot/CONFIGURACION_TELEGRAM.md).

# 2. Base de datos local (requiere Docker; verificada el 2026-11-11)
# Detectar puertos primero (Test-NetConnection a 5432 y 5433):
# POSTGRES_PORT es el primer puerto libre. Ver la guía, paso 8.
docker compose config --quiet
docker compose up -d postgres
docker compose exec postgres pg_isready -U dosisalerta -d dosisalerta

# 3. Backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-lock.txt
pip install -e . --no-deps
alembic upgrade head
uvicorn app.main:app --reload --port 8000
# API en http://localhost:8000 — documentación en http://localhost:8000/docs
# Pruebas (en otra terminal, desde backend/): pytest (546 passed + 1 fallo conocido)

# 4. Frontend
cd ..\frontend
npm ci
Copy-Item .env.example .env
npm run dev
# Web en http://localhost:5173
```

### Linux / macOS

```bash
# 1. Variables de entorno (nunca subir .env a Git)
cp .env.example .env
# Editar .env: contraseña de PostgreSQL y POSTGRES_PORT con el
# primer puerto libre (ver docs/GUIA_INSTALACION_WINDOWS.md,
# paso 8). Generar los tres secretos (JWT_SECRET,
# CAREGIVER_LINK_SECRET, TELEGRAM_LINK_SECRET, >=32 caracteres
# cada uno; ver .env.example). Sin ellos el backend no arranca.
# TELEGRAM_BOT_TOKEN queda pendiente hasta tener el token real
# de BotFather (ver docs/bot/CONFIGURACION_TELEGRAM.md).

# 2. Base de datos local (requiere Docker; verificada el 2026-11-11)
docker compose config --quiet
docker compose up -d postgres
docker compose exec postgres pg_isready -U dosisalerta -d dosisalerta

# 3. Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
pip install -e . --no-deps
alembic upgrade head
uvicorn app.main:app --reload --port 8000
# API en http://localhost:8000 — documentación en http://localhost:8000/docs
# Pruebas (en otra terminal, desde backend/): pytest (546 passed + 1 fallo conocido)

# 4. Frontend
cd ../frontend
npm ci
cp .env.example .env
npm run dev
# Web en http://localhost:5173
```

El bot de Telegram (Fase 6, segundo proceso, mismo código y BD) se
ejecuta con `python -m app.bot.main` **solo con el token real de
BotFather en `.env`**. Sin token no arranca (y el programador de
avisos tampoco envía nada). Ver
`docs/bot/CONFIGURACION_TELEGRAM.md`.

## Autenticación

Desde la Fase 3, el backend expone autenticación JWT bajo
`/api/v1/auth` (registro, login JSON, refresh con rotación
atómica, logout y perfil). Las variables JWT de `.env.example`
ya son **implementadas** (antes reservadas); Telegram sigue
reservado para la Fase 6.

| Método y ruta | Protegido | Respuesta |
|---|---|---|
| `POST /api/v1/auth/register` | No | 201, usuario + tokens |
| `POST /api/v1/auth/login` | No (JSON) | 200, access + refresh |
| `POST /api/v1/auth/refresh` | No (refresh token) | 200, tokens nuevos |
| `POST /api/v1/auth/logout` | No (refresh token) | 200, `{"detail": "Sesión cerrada"}` |
| `GET /api/v1/auth/me` | Sí (`current_user`) | 200, perfil sin `password_hash` |
| `PATCH /api/v1/auth/me` | Sí (`current_user`) | 200, perfil actualizado (zona horaria; recalcula solo las `PENDIENTE` futuras) |

- Contraseñas con bcrypt (mínimo 8 caracteres, máximo 72 bytes
  UTF-8). Nunca se guardan ni se devuelven en claro.
- Access token JWT HS256 (60 minutos), refresh token opaco de
  7 días guardado solo como hash SHA-256, con rotación atómica
  (`UPDATE ... RETURNING`): de 5 renovaciones simultáneas con el
  mismo token, exactamente 1 tiene éxito.
- En Swagger (`/docs`), el diálogo "Authorize" acepta el access
  token pegado directamente (`HTTPBearer`); el login sigue
  siendo JSON.
- **Limitación expresa:** revocar el refresh token (logout)
  impide renovar la sesión, pero el access token emitido antes
  sigue válido hasta su expiración (hasta 60 minutos). Es el
  compromiso aceptado del JWT sin estado; la revocación total de
  access tokens queda fuera de la Fase 3.

## Endpoints principales (`/api/v1`, todos con JWT salvo registro/login)

| Recurso | Rutas | Notas |
|---|---|---|
| Medicamentos | `GET/POST /medications`, `GET/PATCH /medications/{id}`, `POST /medications/{id}/deactivate`, `POST /medications/{id}/reactivate` | Catálogo propio del usuario; desactivar cancela sus `PENDIENTE` futuras (motivo `MEDICATION_DEACTIVATED`) sin borrar el historial |
| Tratamientos | `GET/POST /treatments`, `GET/PATCH /treatments/{id}`, `POST /treatments/{id}/pause`, `/resume`, `/cancel`, `/complete`, `POST /treatments/{id}/medications` | Estados ACTIVO/PAUSADO/COMPLETADO/CANCELADO; cada medicamento con dosis y horarios (DIARIO, DIAS_SEMANA, INTERVALO_DIAS) |
| Recordatorios | `GET /reminders/history`, `POST /reminders/{id}/confirm`, `POST /reminders/{id}/postpone` | Historial con los 8 estados, paginación `limit` (def. 50) + `offset`; posponer 15/30/60 min (máx. 3 por cadena); confirmación idempotente |
| Estadísticas | `GET /stats/compliance` | Cumplimiento con gracia de 30 min inclusiva; agrupación `day/week/month/medication`; canceladas con motivo conocido fuera del denominador |
| Cuidadores | `POST /caregivers/invite`, `POST /caregivers/accept-code`, `GET /caregivers`, `POST /caregivers/{id}/accept`, `PATCH /caregivers/{id}/permissions`, `POST /caregivers/{id}/revoke`, `GET /caregivers/audit` | Vínculo muchos a muchos, 8 permisos en NO por defecto, sin permiso para confirmar dosis; revocación inmediata; auditoría completa |
| Telegram | `POST /telegram/link`, `POST /telegram/unlink`, `GET /telegram/status` | Código de vinculación de un solo uso (10 caracteres, 15 min); el código solo se muestra una vez |

El cuidador accede a los datos de su paciente con
`?patient_id=<id>` en medicamentos, tratamientos, historial y
estadísticas, siempre con vínculo ACTIVO y el permiso concreto;
sin él, 403 con registro `ACCESS_DENIED`. El cuidador nunca
confirma ni pospone dosis. Detalle y contratos en
`backend/README.md` y `docs/database/RELACIONES_CUIDADORES.md`.

## Integración con Telegram

1. El usuario, ya con sesión en la web, pide vincular Telegram y
   recibe un **código de vinculación** de un solo uso, con vencimiento
   (15 minutos). Hoy se pide por la API (`POST /api/v1/telegram/link`);
   **todavía no hay pantalla web para pedirlo desde el perfil** (Fase 8).
2. En Telegram abre el bot y envía `/vincular <código>`.
3. El bot valida el código contra el backend (mismo servicio que la
   web), guarda el `chat_id` y marca la cuenta como vinculada.
4. Desde entonces, el motor de recordatorios envía cada aviso a ese
   `chat_id`, con botones **Tomada** y **Posponer**. El programador
   está apagado por defecto (`SCHEDULER_ENABLED=false`): **sin token
   real de BotFather no se envía ningún aviso** (verificado en la
   Etapa 7: 0 filas ENVIADA/ENVIANDO en la base de desarrollo).
5. Pulsar un botón ejecuta el mismo servicio que usaría la web: la
   toma queda registrada y la web la muestra en el historial sin
   necesidad de ninguna sincronización manual.
6. El bot nunca toca PostgreSQL directamente y nunca guarda el token
   del bot en el código: solo vive en `.env`.

Estado actual (2026-11-22): el bot existe y está probado sobre
servicios reales (7 comandos, 29 callbacks, 19 pruebas de flujo),
pero **nunca ha corrido como proceso persistente ni ha enviado un
aviso real** porque el token sigue siendo un marcador. Tampoco
existe aún la pantalla web de vinculación, y **crear tratamientos
desde el bot no está implementado** (RF18 parcial). Ver
`docs/bot/CONFIGURACION_TELEGRAM.md` y `INFORME_ETAPA6_TELEGRAM.md`.

Modo de recepción en desarrollo: **polling** con python-telegram-bot
(no requiere dominio público ni HTTPS). El webhook queda como opción
futura solo si hay despliegue con dominio y TLS; ver
`docs/decisions/DECISIONES_TECNICAS.md`.

## Integrantes

> **Actualizado el 2026-11-22.** El equipo son Diomar Ochoa (líder),
> Jaider Toro Camacho, Roderic Gallardo y Maisha (apellido por
> confirmar). Requisito académico cumplido por los cuatro:
> **mínimo 5 commits descriptivos por integrante**.

| Integrante | Rol / módulo a cargo | Commits |
|---|---|---|
| Diomar Ochoa | Líder: coordinación, revisión, fusión, docs, Fase 9 | 28 |
| Jaider Toro Camacho | Fase 4 (API) + Fase 5 (motor) | 5 |
| Roderic Gallardo | Fase 7 (historial/estadísticas) + Fase 8 (web) | 5 |
| Maisha | Fase 6 (bot) + Fase 8 (web) | 5 |

Requisito académico: **mínimo 5 commits descriptivos por integrante**,
con la convención `feat:`, `fix:`, `docs:`, `refactor:`, `test:`,
`build:`, `style:`. La distribución propuesta está en
`docs/architecture/ROADMAP.md`. No se hacen commits automáticos.

## Uso de IA

> Sección exigida por la asignatura. Léase antes de defender el proyecto.

- **Qué hizo la IA en la Fase 0:** ayudar a redactar esta arquitectura,
  el modelo de datos, el roadmap y la documentación, y a revisar la
  coherencia entre la web, el bot y la base de datos. La Fase 0 no
  contiene código generado listo para entregar: es diseño y
  planificación.
- **Qué hizo la IA en la Fase 1:** escribir el backend FastAPI
  (`/health`, CORS, configuración), la prueba Pytest, el frontend
  React inicial y esta documentación, ejecutando de verdad las
  pruebas y los servidores en el entorno de desarrollo, y dejando
  constancia de lo que en ese momento no se pudo ejecutar
  (PostgreSQL sin Docker en ese entorno; verificado después, el
  2026-11-11, en el PC del equipo).
  Todo el código de la Fase 1 está en el repositorio para leerlo y
  defenderlo; lo que no existe todavía (autenticación,
  recordatorios, bot completo) no se finge en ningún archivo.
- **Qué hizo la IA en la Fase 2:** escribir los modelos SQLAlchemy
  de las 13 tablas y la migración inicial Alembic `f2a17166bccd`,
  ejecutando de verdad las 31 pruebas de modelos contra
  PostgreSQL 17.11 real (suite completa: 43 pasadas) y
  `alembic revision --autogenerate` sin diferencias.
- **Qué hizo la IA en la Fase 3:** escribir la autenticación JWT
  (registro atómico, login JSON, refresh con rotación atómica,
  logout, dependencia `current_user` con `HTTPBearer`), la
  migración UNIQUE en `refresh_tokens.token_hash` y las 49
  pruebas nuevas (12 unitarias + 37 de integración), ejecutando
  de verdad la suite completa contra PostgreSQL 17.11 real
  (92 pasadas, 0 fallos, tras la corrección robusta del test de
  head). La limitación de que el access token sigue válido hasta
  60 minutos tras el logout está documentada, no oculta.
- **Qué hizo la IA en las Fases 4–9:** escribir medicamentos,
  tratamientos y horarios (Fase 4); el motor de recordatorios
  con su heap, scheduler, reconciliador y top-up (Fase 5); el
  bot de Telegram sobre servicios reales con sus pruebas de
  estructura y de flujo (Fase 6); el plan de la Fase 7 con las
  once decisiones D-1 a D-11, los endpoints de historial y
  estadísticas y sus 122 pruebas formales; la aplicación web
  completa (Fase 8: historial, estadísticas, cuidadores,
  calendario, cambio de zona horaria); y la verificación y
  auditoría de las Etapas 7–9 (corrección DST, auditoría de
  permisos con un defecto real encontrado y corregido, ciclo de
  la migración 14, documentación). En cada fase, la IA ejecutó
  de verdad las pruebas y los servidores (suite final: 546
  pasadas + 1 fallo conocido preexistente; build del frontend
  en verde) y dejó constancia de lo no verificado (token real
  de Telegram, comprobación visual a 390 px, creación de
  tratamientos desde el bot, UI web de vinculación).
- **Qué NO hace la IA por el equipo:** no sustituye la comprensión del
  código. En la sustentación presencial de 10 minutos, cada integrante
  debe poder explicar su módulo: qué hace, por qué se diseñó así y
  dónde puede fallar. Un integrante que no pueda explicar su parte
  pone en riesgo la nota del equipo, aunque el código funcione.
- **Reglas de uso durante el desarrollo:**
  1. Todo código sugerido por IA se lee, se prueba con Pytest y se
     revisa antes de hacer commit. Nada se sube sin entenderlo.
  2. Nunca se comparten con la IA credenciales, tokens de Telegram,
     contraseñas ni el contenido de `.env`.
  3. Los errores y las decisiones que la IA proponga y el equipo
     rechace quedan registrados en `docs/decisions/DECISIONES_TECNICAS.md`.
  4. La documentación indica siempre qué está probado y qué está
     previsto: en la Fase 0, nada de ejecución está probado todavía.
- **Declaración:** el uso de IA en este proyecto es asistencial y
  declarado. El trabajo, las pruebas y la defensa son del equipo.

## Documentación

- Arquitectura: `docs/architecture/ARQUITECTURA.md`
- Requisitos y casos de uso: `docs/architecture/REQUISITOS.md`
- Roadmap por fases: `docs/architecture/ROADMAP.md`
- Modelo de datos: `docs/database/MODELO_DATOS.md`
- Decisiones técnicas: `docs/decisions/DECISIONES_TECNICAS.md`
- Diagramas: `docs/diagrams/DIAGRAMAS.md`
- Estado del proyecto: `ESTADO_PROYECTO.md`

## Limitaciones conocidas (2026-11-22, no ocultar)

1. **Sin token real de Telegram:** el bot nunca ha corrido como
   proceso persistente ni ha enviado un aviso real. El programador
   está apagado por defecto.
2. **Sin UI web de vinculación de Telegram:** vincular se hace por
   la API (`POST /api/v1/telegram/link`); el perfil web no tiene
   todavía la pantalla (Fase 8).
3. **RF18 parcial:** crear tratamientos desde el bot no está
   implementado. Crear/modificar medicamentos y cambiar el estado
   de tratamientos desde el bot, sí.
4. **Comandos de BotFather sin manejador:** 13 registrados
   (lista exacta por confirmar); 7 implementados. Diomar debe
   decidir si se quitan de BotFather o se implementan.
5. **Access token válido hasta 60 minutos tras el logout**
   (compromiso aceptado del JWT sin estado).
6. **Sin rate limiting en autenticación** y sin endpoint de cambio
   de contraseña (hallazgos de auditoría, abiertos).
7. **Comprobación visual a 390 px pendiente en el PC:** la web se
   verificó con componentes reales renderizados contra la API
   real, no con capturas de pantalla.
8. **Suite con 1 fallo conocido preexistente** (el marcador del
   token en `.env` se filtra al entorno de un test).

## Fecha límite

**25 de noviembre de 2026, 12:00 m.** El plan para llegar a esa fecha,
con margen para ensayar la sustentación, está en el roadmap. El 25 en
la mañana no se desarrolla: solo se entrega.
