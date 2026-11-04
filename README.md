# DOSISALERTA

> **Estado: Fase 1 — Implementada, pendiente de revisión.**
> Ya existe backend FastAPI con `GET /health` y frontend React con
> pantalla inicial. Todavía no hay modelos, autenticación,
> medicamentos ni recordatorios. No se ha hecho ningún commit ni push.
> El repositorio público existe, vacío, en
> https://github.com/DiomarOchoa/DOSISALERTA; el primer push se hace
> solo tras revisar esta fase.

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
      inicial (implementada, pendiente de revisión; PostgreSQL sin
      ejecutar todavía por falta de Docker en el entorno de desarrollo).
- [ ] Fase 2: modelos y base de datos PostgreSQL.
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
| Lenguaje backend | Python | 3.12 o superior (único backend) |
| API | FastAPI + Uvicorn | Documentación OpenAPI/Swagger automática |
| ORM y migraciones | SQLAlchemy 2.0 (async) + Alembic | Driver `asyncpg` |
| Validación | Pydantic v2 | Esquemas de entrada y salida |
| Configuración | python-dotenv | Secretos solo en `.env`, nunca en el repo |
| Base de datos | PostgreSQL | 17-alpine en Docker (desarrollo) |
| Bot | python-telegram-bot | Polling en desarrollo (ver decisiones) |
| Autenticación | JWT (PyJWT) + bcrypt | Access 60 min, refresh 7 días |
| Pruebas | Pytest + pytest-asyncio | Unitarias y de API |
| Frontend | React + Vite + TypeScript | CSS moderno, sin framework CSS pesado |
| Entorno | Docker y Docker Compose | Solo PostgreSQL (sin ejecutar todavía en el entorno de la Fase 1) |
| Control de versiones | Git y GitHub | Repositorio público creado, vacío, sin push todavía |

Versiones verificadas en la Fase 1 (entorno de desarrollo: Python
3.12.3, Node.js 24.22.1, npm 10.9.4): FastAPI 0.162.0, Uvicorn
0.54.0, Pydantic 2.14.2, Pytest 9.2.0, React 19.3.1, Vite 6.4.5,
TypeScript 5.9.3. Detalle completo en `backend/README.md` y
`frontend/README.md`.

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

## Requisitos previos (para la Fase 1)

- Python 3.12 o superior.
- Node.js 20.19+ o 22 LTS (para el frontend, Fase 1/8).
- Docker y Docker Compose (para PostgreSQL local), o un PostgreSQL
  17 instalado localmente.
- Git.
- Una cuenta de Telegram y un bot creado con @BotFather (solo se
  necesita el token en la Fase 6; no se necesita para la Fase 1).

## Instalación y ejecución — Fase 1 (verificada, salvo Docker)

> Backend y frontend se probaron de verdad en la Fase 1 (ver
> `ESTADO_PROYECTO.md`). PostgreSQL **no** se ejecutó porque en el
> entorno de desarrollo de la Fase 1 no hay Docker: esa comprobación
> queda pendiente en un PC con Docker. No ejecutar `alembic`
> todavía: no hay migraciones hasta la Fase 2.

### Windows PowerShell

```powershell
# 1. Variables de entorno (nunca subir .env a Git)
Copy-Item .env.example .env
# Editar .env: contraseña de PostgreSQL

# 2. Base de datos local (requiere Docker; pendiente de verificar)
docker compose up -d postgres
docker compose exec postgres pg_isready -U dosisalerta -d dosisalerta

# 3. Backend (Fase 1)
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
# API en http://localhost:8000 — documentación en http://localhost:8000/docs
# Pruebas (en otra terminal, desde backend/): pytest

# 4. Frontend (Fase 1)
cd ..\frontend
npm install
Copy-Item .env.example .env
npm run dev
# Web en http://localhost:5173
```

### Linux / macOS

```bash
# 1. Variables de entorno (nunca subir .env a Git)
cp .env.example .env
# Editar .env: contraseña de PostgreSQL

# 2. Base de datos local (requiere Docker; pendiente de verificar)
docker compose up -d postgres
docker compose exec postgres pg_isready -U dosisalerta -d dosisalerta

# 3. Backend (Fase 1)
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
# API en http://localhost:8000 — documentación en http://localhost:8000/docs
# Pruebas (en otra terminal, desde backend/): pytest

# 4. Frontend (Fase 1)
cd ../frontend
npm install
cp .env.example .env
npm run dev
# Web en http://localhost:5173
```

El bot de Telegram (Fase 6, segundo proceso, mismo código y BD) se
ejecuta con `python -m app.bot.main` **solo a partir de la Fase 6**;
en la Fase 1 ese módulo no existe todavía y no debe ejecutarse.

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

> **Pendiente de completar antes de publicar el repositorio.**
> No se inventan nombres: esta tabla la debe completar el equipo y
> cada integrante debe poder explicar el módulo que firma.

| Integrante | Rol / módulo a cargo | Commits |
|---|---|---|
| Por completar | Por asignar | 0 (Fase 0, sin commits) |
| Por completar | Por asignar | 0 (Fase 0, sin commits) |
| Por completar | Por asignar | 0 (Fase 0, sin commits) |

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
  constancia de lo que no se pudo ejecutar (PostgreSQL sin Docker).
  Todo el código de la Fase 1 está en el repositorio para leerlo y
  defenderlo; lo que no existe todavía (modelos, autenticación,
  recordatorios, bot) no se finge en ningún archivo.
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
