# DOSISALERTA

> **Estado: Fases 1 y 2 — Aprobadas y publicadas en GitHub.**
> Ya existe backend FastAPI con `GET /health` y frontend React con
> pantalla inicial, y ya existen los modelos SQLAlchemy de las 13
> tablas con su migración inicial Alembic aplicada. Todavía no hay
> autenticación, medicamentos ni recordatorios. Commits en la rama
> `main`, en https://github.com/DiomarOchoa/DOSISALERTA:
> `2bc7ec8` (Fase 1, 51 archivos, 2026-11-04), `77d0d5c`
> (auditoría Fase 1, 7 archivos, 2026-11-04), `819c44b`
> (correcciones finales Fase 1, 7 archivos, 2026-11-04),
> `e8d4f0e` (documentación de cuidadores, auditoría y IA, 7
> archivos, 2026-11-11) y `5f75de0` (Fase 2, 20 archivos,
> 2026-11-11). HEAD: `5f75de0`.
> Distinción honesta: implementación y revisión están hechas y
> aprobadas; las pruebas de backend y frontend se ejecutaron de
> verdad (ver abajo); PostgreSQL 17.11 se verificó funcionando
> el 2026-11-11 en el contenedor `dosisalerta-postgres`
> (`pg_isready` con "accepting connections", ver
> `docs/ENTORNO_LOCAL.md`). El esqueleto de demostración del bot
> de Telegram existe solo localmente, sin publicar, y su
> integración completa sigue siendo de la Fase 6. La Fase 3 no
> está iniciada ni autorizada.

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

## Características (previstas, por fases)

- [x] Fase 1: entorno, backend FastAPI con `/health` y frontend React
      inicial (aprobada y publicada, commits `2bc7ec8`, `77d0d5c` y
      `819c44b`; PostgreSQL 17.11 verificado el 2026-11-11, ver
      `docs/ENTORNO_LOCAL.md`).
- [x] Fase 2: modelos y base de datos PostgreSQL (aprobada y
      publicada, commits `e8d4f0e` y `5f75de0`; migración inicial
      `f2a17166bccd`, 13 tablas, 31 pruebas de modelos en verde).
- [ ] Fase 3: autenticación JWT y seguridad por usuario.
- [ ] Fase 4: medicamentos, tratamientos, dosis y horarios.
- [ ] Fase 5: motor de recordatorios con cola de prioridad y
      prevención de duplicados.
- [ ] Fase 6: bot de Telegram completo, con los mismos servicios.
- [ ] Fase 7: historial y estadísticas de cumplimiento.
- [ ] Fase 8: aplicación web React completa.
- [ ] Fase 9: pruebas, despliegue y documentación final.

## Tecnologías

| Capa | Tecnología | Versión / nota |
|---|---|---|
| Lenguaje backend | Python | 3.13.4, versión canónica (`requires-python >=3.12,<3.14`) (único backend) |
| API | FastAPI + Uvicorn | Documentación OpenAPI/Swagger automática |
| ORM y migraciones | SQLAlchemy 2.0 (async) + Alembic | Instalado en la Fase 2: SQLAlchemy 2.1.8, Alembic 1.20.1, asyncpg 0.32.0. |
| Validación | Pydantic v2 | Instalado en la Fase 1 (2.14.2). Esquemas de entrada y salida. |
| Configuración | python-dotenv | Instalado en la Fase 1 (1.2.4). Secretos solo en `.env`, nunca en el repo. |
| Base de datos | PostgreSQL | `postgres:17.11-alpine` en Docker (desarrollo). Verificado 17.11 el 2026-11-11; el contenedor publica en el puerto del host 5433 (el 5432 lo ocupa un PostgreSQL 18 nativo). |
| Bot | python-telegram-bot | Esqueleto de demostración local, sin publicar (python-telegram-bot 22.8 en el árbol de trabajo, sin commit). Integración completa en la Fase 6. Polling en desarrollo (ver decisiones). |
| Autenticación | JWT (PyJWT) + bcrypt | Previsto para la Fase 3, no instalado. Access 60 min, refresh 7 días. |
| Pruebas | Pytest + HTTPX | Instalados en la Fase 1 (Pytest 9.2.0, HTTPX 0.28.1). En la Fase 2 se añadió pytest-asyncio 1.4.1.post1 para las 31 pruebas de modelos contra PostgreSQL real. |
| Frontend | React + Vite + TypeScript | CSS moderno, sin framework CSS pesado |
| Entorno | Docker y Docker Compose | Solo PostgreSQL, verificado el 2026-11-11 (ver `docs/ENTORNO_LOCAL.md`) |
| Control de versiones | Git y GitHub | Repositorio público, rama `main`, HEAD `5f75de0`; commits `2bc7ec8`, `77d0d5c`, `819c44b`, `e8d4f0e` y `5f75de0` |

Versiones canónicas (Fase A): Python 3.13.4, Node.js 24.12.0,
npm 11.6.2, PostgreSQL 17.11. Dependencias verificadas: FastAPI
0.162.0, Uvicorn 0.54.0, Pydantic 2.14.2, Pytest 9.2.0, React
19.3.1, Vite 6.4.5, TypeScript 5.9.3. En el PC del equipo,
`pytest` dio 43 passed (12 de la Fase 1 y 31 de la Fase 2),
`uvicorn` arrancó en 8000, `/health` respondió
`{"status":"ok","app":"DosisAlerta","version":"0.1.0"}` y el
frontend en 5173 mostró "Backend en línea (versión 0.1.0)".
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

## Requisitos previos (Fases 1 y 2)

- Python 3.13.4 (versión canónica).
- Node.js 24.12.0 y npm 11.6.2 (versiones canónicas).
- Docker y Docker Compose (para PostgreSQL local).
- Git.
- Una cuenta de GitHub propia (para contribuir; ver
  `docs/GUIA_INSTALACION_WINDOWS.md`, paso 20).

> Telegram no es un requisito previo: el bot es de la Fase 6, sin
> iniciar, y no se necesita ningún token de BotFather para instalar
> el entorno común.

## Instalación y ejecución — Fases 1 y 2 (verificadas)

> Backend y frontend se probaron de verdad en la Fase 1 (ver
> `ESTADO_PROYECTO.md`). PostgreSQL se verificó el 2026-11-11 en
> el PC del equipo (17.11, `pg_isready` con "accepting
> connections", ver `docs/ENTORNO_LOCAL.md`); Docker Desktop
> estaba apagado el 2026-11-17, sin verificación en vivo ese día.
> Las migraciones existen desde la Fase 2 (`alembic upgrade head`
> crea las 13 tablas); nunca usar `create_all` como mecanismo de
> evolución del esquema.

### Windows PowerShell

```powershell
# 1. Variables de entorno (nunca subir .env a Git)
Copy-Item .env.example .env
# Editar .env: contraseña de PostgreSQL y POSTGRES_PORT según el
# paso 8 de docs/GUIA_INSTALACION_WINDOWS.md (detectar puertos
# primero). Ver .env.example: 9 variables implementadas; JWT y
# Telegram son reservadas para las Fases 3 y 6.

# 2. Base de datos local (requiere Docker; verificada el 2026-11-11)
# Detectar puertos primero (Test-NetConnection a 5432 y 5433):
# POSTGRES_PORT es el primer puerto libre. Ver la guía, paso 8.
docker compose config --quiet
docker compose up -d postgres
docker compose exec postgres pg_isready -U dosisalerta -d dosisalerta

# 3. Backend (Fases 1 y 2)
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-lock.txt
pip install -e . --no-deps
alembic upgrade head
uvicorn app.main:app --reload --port 8000
# API en http://localhost:8000 — documentación en http://localhost:8000/docs
# Pruebas (en otra terminal, desde backend/): pytest (43 passed)

# 4. Frontend (Fases 1 y 2)
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
# paso 8). Ver .env.example: 9 variables implementadas; JWT y
# Telegram son reservadas para las Fases 3 y 6.

# 2. Base de datos local (requiere Docker; verificada el 2026-11-11)
docker compose config --quiet
docker compose up -d postgres
docker compose exec postgres pg_isready -U dosisalerta -d dosisalerta

# 3. Backend (Fases 1 y 2)
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
pip install -e . --no-deps
alembic upgrade head
uvicorn app.main:app --reload --port 8000
# API en http://localhost:8000 — documentación en http://localhost:8000/docs
# Pruebas (en otra terminal, desde backend/): pytest (43 passed)

# 4. Frontend (Fases 1 y 2)
cd ../frontend
npm ci
cp .env.example .env
npm run dev
# Web en http://localhost:5173
```

El bot de Telegram (Fase 6, segundo proceso, mismo código y BD) se
ejecuta con `python -m app.bot.main` **solo a partir de la Fase 6**.
Existe un esqueleto de demostración con datos ficticios, solo
local y sin publicar, que no debe ejecutarse como integración
real: no toca PostgreSQL, ni JWT, ni servicios reales.

## Integración con Telegram

1. El usuario, ya con sesión en la web, pide vincular Telegram y
   recibe un **código de vinculación** de un solo uso, con vencimiento.
2. En Telegram abre el bot y envía `/vincular <código>`.
3. El bot valida el código contra el backend (mismo servicio que la
   web), guarda el `chat_id` y marca la cuenta como vinculada.
4. Desde entonces, el motor de recordatorios envía cada aviso a ese
   `chat_id`, con botones **Tomada** y **Posponer**.
5. Pulsar un botón ejecuta el mismo servicio que usaría la web: la
   toma queda registrada y la web la muestra en el historial sin
   necesidad de ninguna sincronización manual.
6. El bot nunca toca PostgreSQL directamente y nunca guarda el token
   del bot en el código: solo vive en `.env`.

Modo de recepción en desarrollo: **polling** con python-telegram-bot
(no requiere dominio público ni HTTPS). El webhook queda como opción
futura solo si hay despliegue con dominio y TLS; ver
`docs/decisions/DECISIONES_TECNICAS.md`.

## Integrantes

> **Pendiente de completar.**
> No se inventan nombres: esta tabla la debe completar el equipo y
> cada integrante debe poder explicar el módulo que firma. El
> repositorio ya está publicado y tiene 5 commits totales
> (`2bc7ec8`, `77d0d5c`, `819c44b`, `e8d4f0e` y `5f75de0`); el
> reparto de commits por integrante queda pendiente hasta que se
> completen los nombres, así que no se asigna ningún commit a
> nadie en esta tabla todavía.

| Integrante | Rol / módulo a cargo | Commits |
|---|---|---|
| Por completar | Por asignar | Pendiente de reparto |
| Por completar | Por asignar | Pendiente de reparto |
| Por completar | Por asignar | Pendiente de reparto |

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

## Fecha límite

**25 de noviembre de 2026, 12:00 m.** El plan para llegar a esa fecha,
con margen para ensayar la sustentación, está en el roadmap. El 25 en
la mañana no se desarrolla: solo se entrega.
