# ESTADO_PROYECTO.md — DosisAlerta

Última actualización: **2026-11-04 — Fase 1 APROBADA Y PUBLICADA
en GitHub; correcciones finales preparadas, PENDIENTES DE TERCER
COMMIT (sin hacer todavía).**
**No se ha iniciado la Fase 2. Commits en la rama `main`,
publicados el 2026-11-04: `2bc7ec8` (implementación, 51 archivos)
y `77d0d5c` (auditoría, 7 archivos).**

## Fase actual

**FASE 1: Configuración del entorno y backend Python — APROBADA Y
PUBLICADA. Cierre pendiente solo de PostgreSQL con Docker.**

Lo que significa "aprobada y publicada" aquí es preciso: el equipo
revisó la Fase 1, la aprobó y la subió a GitHub desde su PC. El
backend FastAPI arranca y responde `GET /health` con 200, las 3
pruebas Pytest pasan (en el entorno de desarrollo y en el PC), el
frontend Vite + React + TypeScript arranca en 5173, su build
compila sin errores y su botón "Comprobar backend" mostró "Backend
en línea (versión 0.1.0)" en el PC. No significa que la Fase 1 esté
cerrada por completo: PostgreSQL no se ha ejecutado en ningún
entorno todavía (ver "Problemas pendientes"). La Fase 2 no se
inicia hasta que se autorice por separado.

## Objetivos completados (Fase 0)

- [x] Estructura definitiva del repositorio (backend, frontend, docs, docker).
- [x] Arquitectura documentada: monolito modular Python + FastAPI,
      dos procesos (API y bot) que comparten servicios y PostgreSQL.
- [x] Comunicación bidireccional web ↔ Telegram documentada paso a paso.
- [x] Modelo de datos diseñado: 11 tablas, relaciones, restricciones e índices.
- [x] Motor de recordatorios diseñado: cola de prioridad, persistencia,
      concurrencia y prevención de duplicados.
- [x] Revisión técnica aplicada (2026-11-04): promesa de idempotencia
      corregida a entrega al menos una vez / efecto exactamente una
      vez, `notification_logs` con `attempted_at` y `sent_at` NULL,
      estado `AMBIGUA` y reconciliación, FK compuestas contra cruces
      entre cuentas, códigos Telegram con `secrets` + HMAC + límite
      de intentos, y zonas horarias UTC/local/DST documentadas.
- [x] Requisitos funcionales, no funcionales y casos de uso.
- [x] Decisiones técnicas justificadas, con alternativas rechazadas.
- [x] Diagramas en Mermaid: arquitectura, entidad-relación, casos de
      uso y flujo de notificaciones.
- [x] Roadmap Fases 0–9 con tareas, pruebas, aceptación y commits.
- [x] README con sección "Uso de IA" exigida por la asignatura.
- [x] `.gitignore`, `.env.example` y `docker-compose.yml` (PostgreSQL).

## Objetivos completados (Fase 1)

- [x] Backend FastAPI modular: `pyproject.toml` (sin
      `requirements.txt` duplicado), configuración central desde
      `.env`, aplicación con factoría `create_app`, CORS solo para
      `http://localhost:5173` en desarrollo.
- [x] Endpoint `GET /health` (200, JSON `status: ok`) y su gemelo
      `GET /api/v1/health` para el frontend; documentación OpenAPI
      automática en `/docs`.
- [x] Prueba Pytest del endpoint de salud: 3 pruebas en verde
      (`/health`, `/api/v1/health`, 404 en ruta inexistente), sin
      servidor real ni base de datos.
- [x] Frontend Vite + React + TypeScript: pantalla inicial con
      botón "Comprobar backend" contra `/api/v1/health`, URL por
      `VITE_API_URL`, TypeScript estricto, `npm run build` sin
      errores y `npm run dev` respondiendo HTTP 200 en 5173.
- [x] Docker Compose revisado: puerto del host configurable con
      `POSTGRES_PORT`, volumen `postgres-data`, imagen
      `postgres:17-alpine`, sintaxis YAML validada. **No ejecutado**
      (sin Docker en el entorno de la Fase 1): ver pendientes.
- [x] Documentación actualizada: `README.md`, `backend/README.md`,
      `frontend/README.md` y `docker/README.md`, con comandos para
      Windows PowerShell y para Linux/macOS, versiones verificadas
      y limitaciones declaradas.

## Archivos creados en la Fase 1

- `backend/pyproject.toml`, `backend/app/main.py`,
  `backend/app/core/config.py`,
  `backend/app/api/routers/health.py`,
  `backend/app/tests/test_health.py`, y `__init__.py` de cada
  paquete (`core`, `config`, `database`, `models`, `schemas`,
  `repositories`, `services`, `api`, `api/routers`, `bot`,
  `scheduler`, `algorithms`, `utils`, `tests`). Los paquetes de
  fases posteriores solo contienen un docstring: no fingen código.
- `frontend/package.json`, `frontend/package-lock.json`,
  `frontend/vite.config.ts`, `frontend/tsconfig.json`,
  `frontend/index.html`, `frontend/.env.example`,
  `frontend/src/main.tsx`, `frontend/src/App.tsx`,
  `frontend/src/styles.css`, `frontend/src/vite-env.d.ts`, y las
  carpetas vacías `src/{components,pages,services,hooks,context,styles}`.
- `frontend/package-lock.json` se versiona (fija las versiones
  exactas del frontend). Los directorios `backend/.venv`,
  `backend/dosisalerta.egg-info`, `frontend/node_modules` y
  `frontend/dist` **no** se versionan (están en `.gitignore`) y no
  deben copiarse al PC: en el PC se regeneran con `pip install` y
  `npm install`.

## Archivos modificados en la Fase 1

- `docker-compose.yml`: puerto del host configurable
  (`${POSTGRES_PORT:-5432}:5432`) y encabezado actualizado a
  Fase 1, sin cambiar imagen, volumen ni healthcheck.
- `README.md`, `backend/README.md`, `frontend/README.md`,
  `docker/README.md`: estado Fase 1, comandos verificados,
  versiones y limitaciones (ver arriba).
- Ningún documento de la Fase 0 (arquitectura, modelo, requisitos,
  roadmap, decisiones, diagramas) se modificó en la Fase 1: la
  implementación respeta esas decisiones y no las reescribe.

## Archivos creados y modificados en la Fase 0

### Creados en esta corrección (Python + FastAPI)

- `README.md`
- `ESTADO_PROYECTO.md`
- `docs/architecture/ARQUITECTURA.md`
- `docs/architecture/REQUISITOS.md`
- `docs/architecture/ROADMAP.md`
- `docs/database/MODELO_DATOS.md`
- `docs/decisions/DECISIONES_TECNICAS.md`
- `docs/diagrams/DIAGRAMAS.md`
- `backend/README.md`, `frontend/README.md`, `docker/README.md`,
  `docs/presentation/README.md` (explican qué irá en cada carpeta y por
  qué todavía está vacía).
- Estructura de carpetas vacías (sin código) bajo `backend/app/` y
  `frontend/src/`, según la estructura definitiva.

### Conservados y revisados (no reinventados)

- `docker-compose.yml`: servicio `postgres` revisado y conservado tal
  cual en imagen (`postgres:17-alpine`), puerto (`5432`), volumen
  (`postgres-data`) y healthcheck (`pg_isready`). Solo se actualizaron
  los comentarios, que hacían referencia a un archivo de otro stack, y
  se dejó constancia de que **no está probado** (en este entorno no hay
  Docker instalado).
- `docs/presentation/README.md`: reservado para la Fase 9, sin material
  inventado de un sistema que aún no existe.

### Sustituidos (corrección exigida por el requisito oficial)

- `.gitignore`, `.env.example`, `backend/README.md` y
  `frontend/README.md` del borrador anterior, interrumpido: ese borrador
  usaba un stack distinto al exigido por la asignatura y una URL de
  base de datos y un puerto de backend propios de ese stack. Se
  sustituyeron por su equivalente Python/FastAPI (ver auditoría en el
  informe de entrega). **No se mantiene ninguna segunda arquitectura:**
  en los documentos de la Fase 0 solo existe la arquitectura Python.
- No se eliminó ningún archivo del usuario: el borrador anterior era
  trabajo de esta misma sesión, no material entregado por el equipo, y
  no había ningún repositorio Git dentro de `DosisAlerta/` que conservar.

## Decisiones tomadas (resumen)

1. **Python 3.12+ con FastAPI** como único backend. Cumple el requisito
   oficial de aplicación real en Python.
2. **Monolito modular**, no microservicios: un equipo universitario no
   gana nada partiendo el sistema en servicios desplegables separados.
3. **Dos procesos, un código, una BD:** API (Uvicorn) + bot (polling).
   El scheduler vive en el proceso API y envía por la API de Telegram;
   el bot solo atiende órdenes entrantes.
4. **Polling, no webhook**, en desarrollo: no exige dominio ni HTTPS.
5. **SQLAlchemy async + Alembic**, nunca `create_all` en producción del
   proyecto: las migraciones son la historia real del esquema.
6. **TypeScript** en el frontend, no JavaScript plano.
7. **pyproject.toml** como única fuente de dependencias Python (el
   requisito pide `requirements.txt` **o** `pyproject.toml`).
8. **Cola de prioridad propia** detrás de una interfaz, con `heapq`
   como respaldo: se demuestra la estructura sin poner en riesgo el
   envío si la implementación propia falla sus pruebas.
9. **Historial inmutable en la práctica:** cancelar o desactivar, nunca
   borrar tomas ni recordatorios con DELETE.
10. **Idempotencia realista (revisión técnica):** entrega al menos una
    vez, efecto exactamente una vez, ningún fallo silencioso. Telegram
    no ofrece idempotencia, así que no se promete envío exactamente
    una vez; los intentos ambiguos quedan `AMBIGUA` y se reconcilian.
11. **Integridad entre cuentas:** servicio + FK compuestas
    `(padre_id, user_id)`; una FK simple no basta para impedir cruces.
12. **Códigos Telegram seguros:** `secrets`, 10 caracteres, HMAC con
    secreto dedicado, 15 minutos, un solo uso, 5 fallos por `chat_id`
    en 15 minutos, mensaje genérico ante cualquier fallo.
13. **Zonas horarias:** UTC dentro, hora de pared fuera, DST con
    reglas explícitas, cambio de zona recalcula solo los `PENDIENTE`
    futuros.

Detalle y alternativas rechazadas: `docs/decisions/DECISIONES_TECNICAS.md`.

## Problemas pendientes (no ocultar, resolver antes o en la Fase 1)

1. **Nombres de los integrantes:** pendientes. El README los deja
   como "por completar" a propósito; no se inventan. Sin esto no se
   puede repartir los 5 commits por integrante.
2. **Repositorio público — RESUELTO:** creado el 2026-11-04 en
   https://github.com/DiomarOchoa/DOSISALERTA y publicado ese mismo
   día desde el PC del equipo: `git init -b main`, remoto `origin`
   apuntando a esa URL, primer commit `2bc7ec8` ("feat: implement
   Phase 1 - FastAPI backend, React frontend and PostgreSQL
   setup"), 51 archivos, 5228 inserciones, push `main -> main`
   sin errores y sin `.env`, `.venv` ni `node_modules` en lo
   subido. La copia de trabajo donde se escribió la Fase 1 en este
   entorno **sigue sin ser un repositorio Git** (no hay `.git`, ni
   rama, ni remoto aquí): no se inicializó Git en esta copia para
   no crear un segundo repositorio paralelo al del PC. Las
   correcciones de esta auditoría se preparan aquí y se deben
   trasladar al PC para su commit y push, nunca con `git reset
   --hard`, `git clean` destructivo ni force push.
3. **Revisión de la carpeta en el PC (interrumpida, pendiente de
   comprobar por el equipo):** el 2026-11-04 se intentó revisar
   `C:\Users\ASUS\Desktop\PROYECTO_ED2\DOSISALERTA` por Tailscale +
   SSH. El túnel conecta, pero el PC no devolvió respuesta (sin
   aprobación pendiente en el sistema). Antes de reintentar, el
   equipo debe comprobar en el PC: que esté encendido y despierto,
   que Tailscale diga Connected y que OpenSSH Server esté corriendo.
   El script de conexión quedó guardado de forma persistente en
   `workspace/ssh_tailscale.sh` para no perderlo en reinicios.
4. **Docker Compose sin ejecutar (pendiente principal del cierre
   de la Fase 1):** ni en el entorno donde se escribió la Fase 1
   ni en el PC se ha ejecutado todavía PostgreSQL. La sintaxis YAML
   se validó y la configuración es la prevista, pero PostgreSQL no
   se levantó ni respondió a `pg_isready` en ningún entorno. La
   primera ejecución real debe hacerse y registrarse en un PC con
   Docker (ver `docker/README.md` para los comandos exactos) antes
   de dar la Fase 1 por cerrada en base de datos. Mientras tanto,
   backend y frontend funcionan sin BD, porque en la Fase 1 ningún
   endpoint la toca.
5. **Versiones exactas de librerías Python — RESUELTO en la
   auditoría de cierre:** `backend/pyproject.toml` fija ahora las
   versiones exactas verificadas en los dos entornos (FastAPI
   0.162.0, Uvicorn 0.54.0, Pydantic 2.14.2, python-dotenv 1.2.4,
   tzdata 2026.6, Pytest 9.2.0, HTTPX 0.28.1). No se crea un
   `requirements.txt` duplicado ni un archivo de bloqueo aparte:
   `pyproject.toml` sigue siendo la única fuente, y para
   actualizar una versión hay que cambiarla ahí, reinstalar y
   volver a pasar `pytest`, nunca hacer `pip install --upgrade`
   suelto. El frontend ya estaba fijado por
   `frontend/package-lock.json` (usar `npm ci` para una instalación
   exactamente igual a la bloqueada).
6. **Token de Telegram:** no existe todavía en este proyecto. Se crea
   con @BotFather en la Fase 6. No debe pedirse ni guardarse antes.
7. **Calendario ajustado:** quedan 21 días hasta el 25 de noviembre de
   2026 a las 12:00 m. El roadmap propone fechas por fase con el 24
   para ensayo; cualquier retraso se recorta de pulido de la web,
   nunca de persistencia, seguridad o pruebas del motor.
8. **Zona horaria por defecto:** se propone `America/Bogota` como valor
   inicial configurable por usuario, no como regla fija. Confirmarlo en
   la Fase 2 (es un campo en `users.timezone`, no código fijo).

## Auditoría de cierre de la Fase 1 (2026-11-04)

- **Git en el PC (según la terminal del equipo):** rama `main`,
  remoto `origin` = https://github.com/DiomarOchoa/DOSISALERTA,
  commit `2bc7ec8`, 51 archivos, push exitoso. En esta copia de
  trabajo no hay `.git`: la auditoría no pudo comprobar Git aquí
  y no lo finge; el estado Git que se registra es el de la
  terminal del equipo, no una comprobación local.
- **Documentación corregida:** `README.md` y `ESTADO_PROYECTO.md`
  ya no dicen que el repo está vacío ni que no hay push; también
  se actualizaron el estado en `backend/README.md` y
  `frontend/README.md`, y la fila de repositorio en
  `docs/architecture/REQUISITOS.md` y la tarea de la Fase 1 en
  `docs/architecture/ROADMAP.md`, que afirmaban el estado viejo.
- **Dependencias:** `pyproject.toml` con versiones exactas (ver
  punto 5 de pendientes, ya resuelto); frontend fijado por
  `package-lock.json`.
- **Docker/PostgreSQL:** NO verificado en ningún entorno. En este
  entorno no hay Docker (`docker: command not found`), así que
  `docker compose config`, `up -d postgres` y `pg_isready` no se
  ejecutaron aquí y no se simulan. Los comandos exactos para el PC
  están en `docker/README.md`.
- **Backend/frontend re-verificados en esta auditoría:** ver el
  informe de entrega (pytest, `/health`, build y dev). Ninguna
  prueba se declara exitosa sin haberla ejecutado.
- **Auditoría trasladada y publicada:** los cambios de esta
  auditoría se trasladaron al PC y se publicaron como segundo
  commit `77d0d5c` ("docs: audit and close Phase 1, pin dependency
  versions", 7 archivos, 158 inserciones, 69 eliminaciones, push
  `2bc7ec8..77d0d5c` en `main`), sin el ZIP ni `package-lock.json`
  en el commit. La frase anterior, que los dejaba pendientes de
  traslado, quedó corregida por este hecho.

## Correcciones finales de la Fase 1 (2026-11-04, pendientes de tercer commit)

Autorizadas por el equipo tras la revisión final, y preparadas
aquí, sin commit ni push todavía:

- **Documentación:** `README.md`, `ESTADO_PROYECTO.md`,
  `backend/README.md`, `frontend/README.md` y
  `docs/architecture/ROADMAP.md` registran ahora los dos commits
  (`2bc7ec8` y `77d0d5c`), el total de 2 commits, las fechas
  reales (Fase 1 realizada el 2026-11-04, un día antes de lo
  propuesto del 5 al 7 de noviembre) y la distinción entre
  tecnologías instaladas en la Fase 1 y previstas para fases
  posteriores. PostgreSQL sigue sin afirmarse como funcionando:
  sigue pendiente de verificar con Docker.
- **Backend:** `backend/app/core/config.py` valida ahora
  explícitamente `PORT` y `POSTGRES_PORT`: entero entre 1 y
  65535, vacío o ausente usa el defecto, inválido falla al
  arrancar con un error que nombra la variable. Sin cambio de
  arquitectura y sin dependencias nuevas.
- **Pruebas:** nuevo `backend/app/tests/test_config.py` con casos
  para `PORT=abc`, `99999`, `-1`, `0`, `POSTGRES_PORT=xyz`,
  valores válidos, límites 1 y 65535, variables vacías y
  defectos. Las pruebas usan `Settings()` directamente, no la
  configuración cacheada, para no contaminarse entre sí.
- **Verificación de estas correcciones:** ver el informe de
  entrega de esta corrección (pytest completo, uvicorn,
  `/health`, `/api/v1/health`, build y dev del frontend).
  PostgreSQL sigue pendiente, solo en el PC con Docker.

## Próxima fase (SOLO cuando se autorice)

**FASE 2: Modelos de datos y migraciones.**
Ver criterios de aceptación completos en `docs/architecture/ROADMAP.md`,
sección Fase 2. En resumen: modelos SQLAlchemy de las 11 tablas,
migración inicial con Alembic, restricciones y FK compuestas, y
pruebas de que un cruce de cuentas falla por FK. Nada de
autenticación, medicamentos, tratamientos ni bot todavía: eso sigue
siendo de fases posteriores, y la Fase 2 no se inicia hasta que el
equipo autorice y apruebe la Fase 1.
