# DosisAlerta — Entorno local (Windows + Docker + PostgreSQL)

Documento del entorno de desarrollo local. No contiene contraseñas,
tokens ni secretos: solo nombres de variables y comandos.

Estado verificado (2026-11-11): Docker y la configuración están
verificados y PostgreSQL 17.11 funciona: contenedor
`dosisalerta-postgres` en ejecución y `healthy`, `pg_isready`
responde "accepting connections", base de datos `dosisalerta` y
usuario `dosisalerta` confirmados con `SELECT version()` y
`SELECT current_database(), current_user;`. La primera descarga de
la imagen tuvo que hacerse en una terminal interactiva (ver
"Problema conocido" abajo). **Fase 2 COMPLETADA el 2026-11-11:**
migración inicial Alembic `f2a17166bccd` aplicada, 13 tablas en la
base `dosisalerta`, 31 pruebas de modelos en verde. El contenedor
se publica en el puerto del host **5433** por el conflicto con un
PostgreSQL 18 nativo (ver "Problema conocido" abajo).

## 1. Requisitos del entorno

- Windows 10/11 con WSL2.
- Docker Desktop instalado y en ejecución.
- Python 3.12+ (el proyecto usa 3.13.4 en el PC).
- Node.js para el frontend (React + Vite + TypeScript).
- PowerShell 5.1.
- Repositorio clonado en `C:\Users\ASUS\Desktop\PROYECTO_ED2\DOSISALERTA`,
  rama `main`.

## 2. Versiones de herramientas verificadas (2026-11-11)

| Herramienta | Versión verificada |
|---|---|
| Docker | 29.9.3 |
| Docker Compose | v5.7.0 |
| Docker Engine | servidor activo, Linux x86_64, WSL2 |
| Recursos Docker | 12 CPU, 11.53 GiB de memoria |
| PostgreSQL (imagen) | postgres:17-alpine |
| Python | 3.13.4 |

## 3. Estructura relevante

- `docker-compose.yml`: define **únicamente** PostgreSQL. El backend
  FastAPI y el frontend React **no** se levantan en Docker en la
  Fase 1: se ejecutan fuera, con `uvicorn` y `npm run dev`.
- Servicio PostgreSQL: nombre `postgres`, contenedor
  `dosisalerta-postgres`, volumen `postgres-data`, puerto del host
  `${POSTGRES_PORT:-5432}` hacia el `5432` del contenedor. En este
  PC `POSTGRES_PORT=5433` en `.env` (ver "Problema conocido":
  el 5432 lo ocupa un PostgreSQL 18 nativo).
- Healthcheck: `pg_isready -U ${POSTGRES_USER:-dosisalerta} -d
  ${POSTGRES_DB:-dosisalerta}`, cada 10 s, timeout 5 s, 5 reintentos.
- `.env`: variables locales. Está en `.gitignore` y **no** se sube
  a Git. Copia de seguridad local: `.env.backup.local` (también
  ignorada por Git).
- `.env.example`: plantilla sin credenciales reales. No modificarla
  con valores reales.

## 4. Cómo iniciar Docker y PostgreSQL

Desde la raíz del proyecto, en PowerShell:

```powershell
cd C:\Users\ASUS\Desktop\PROYECTO_ED2\DOSISALERTA
docker compose config --quiet   # valida la configuracion (debe salir sin error)
docker compose up -d postgres   # inicia SOLO PostgreSQL
docker compose ps               # estado del contenedor
```

No iniciar backend, frontend ni bot desde Docker en esta etapa.

## 5. Cómo comprobar el estado de PostgreSQL

```powershell
docker compose exec postgres pg_isready -U dosisalerta -d dosisalerta
docker compose exec postgres psql -U dosisalerta -d dosisalerta -c 'SELECT version();'
docker compose exec postgres psql -U dosisalerta -d dosisalerta -c 'SELECT current_database(), current_user;'
```

Éxito: `pg_isready` responde "accepting connections", el healthcheck
del contenedor pasa a `healthy`, y las consultas devuelven
PostgreSQL 17 con base de datos `dosisalerta` y usuario `dosisalerta`.

## 6. Cómo detener el servicio sin eliminar los datos

```powershell
docker compose down        # detiene sin borrar el volumen ni los datos
```

**Nunca** ejecutar `docker compose down -v`: borra el volumen
`postgres-data` y todos los datos de prueba.

## 7. Variables de entorno necesarias (solo nombres)

- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `JWT_SECRET`
- `JWT_ALGORITHM`
- `JWT_ACCESS_EXPIRATION_MINUTES`
- `JWT_REFRESH_EXPIRATION_DAYS`
- `TELEGRAM_BOT_TOKEN` (pendiente: sin token real de BotFather aún)
- `TELEGRAM_BOT_USERNAME`
- `TELEGRAM_LINK_SECRET`
- `VITE_API_URL`

Los tres secretos (`POSTGRES_PASSWORD`, `JWT_SECRET`,
`TELEGRAM_LINK_SECRET`) deben ser valores distintos, generados con
un generador criptográficamente seguro (por ejemplo, Python
`secrets`). No reutilizar el mismo secreto en dos variables.
`POSTGRES_PASSWORD` es obligatoria: si falta o está vacía, Compose
falla con "Falta POSTGRES_PASSWORD en .env".

## 8. Problemas conocidos y soluciones

### La descarga de la imagen falla desde SSH con "error getting credentials"

Síntoma:

```text
error getting credentials - err: exit status 1, out: `A specified logon
session does not exist. It may already have been terminated.`
```

Causa: Docker Desktop usa el ayudante de credenciales `desktop`,
que necesita una sesión interactiva de Windows. Una sesión SSH no
la tiene, así que el ayudante falla antes de descargar nada. No es
un problema del `.env` ni del `docker-compose.yml`, y no hay imágenes
locales de Postgres hasta que se resuelve.

Solución: ejecutar **una vez** la descarga en una terminal
PowerShell interactiva del propio PC:

```powershell
cd C:\Users\ASUS\Desktop\PROYECTO_ED2\DOSISALERTA
docker compose up -d postgres
```

Una vez la imagen `postgres:17-alpine` está en local, los siguientes
arranques ya no necesitan descargar y pueden hacerse por SSH.

### El puerto 5432 ya está en uso: hay un PostgreSQL 18 nativo en el PC

Síntoma (2026-11-11): desde el host, las conexiones a
`localhost:5432` fallaban con errores de asyncpg (`WinError 64` /
`ConnectionDoesNotExistError`) y el log del servidor decía
`FATAL: la autenticación password falló para el usuario
'dosisalerta'` con el detalle `No existe el rol 'dosisalerta'`.

Causa: el PC tiene instalado un **PostgreSQL 18 nativo de Windows**
(servicio `postgresql-x64-18`, automático, en ejecución,
`listen_addresses='*'`, puerto 5432, datos en
`C:\Program Files\PostgreSQL\18\data`). Ese servidor es el que
responde en el puerto 5432 del host, no el contenedor Docker
(aunque Docker también publica ese puerto). El rol `dosisalerta`
no existe en ese servidor nativo. **No tocar ni desinstalar el
PostgreSQL 18 nativo: es una instalación propia del PC y puede
servir para otros trabajos.**

Solución aplicada (2026-11-11):

1. Alinear la contraseña del usuario `dosisalerta` dentro del
   contenedor con el valor de `.env`, con
   `ALTER USER dosisalerta WITH PASSWORD '<valor de .env>'`
   ejecutado por `docker exec` con psql (autenticación trust
   dentro del contenedor). Verificador SCRAM comprobado.
2. Cambiar `POSTGRES_PORT=5433` en `.env` (no tocar
   `docker-compose.yml`: ese archivo ya prevé cambiar el puerto
   del host). Recrear el contenedor con `docker compose down`
   (sin `-v`, para conservar el volumen) y
   `docker compose up -d postgres`. El contenedor publica ahora
   `0.0.0.0:5433->5432/tcp`, en estado `healthy`.

Cómo comprobar que se conecta al contenedor correcto: la
conexión a `localhost:5433` debe devolver **PostgreSQL 17.11**
(`SELECT version();`). Si devuelve PostgreSQL 18, se está
llegando al servidor nativo, no al contenedor.

El `pg_isready` por `docker compose exec` sigue funcionando
igual, porque dentro del contenedor sigue siendo el 5432.

### `pg_isready` no responde "accepting connections"

Revisar los logs antes de tocar nada:

```powershell
docker compose logs postgres
```

## 9. Pasos para preparar el entorno en otro computador

1. Clonar el repositorio y entrar en la carpeta del proyecto.
2. Instalar Docker Desktop y abrirlo (WSL2).
3. Copiar `.env.example` a `.env` y completar los valores:
   `POSTGRES_DB=dosisalerta`, `POSTGRES_USER=dosisalerta`,
   generar `POSTGRES_PASSWORD`, `JWT_SECRET` y
   `TELEGRAM_LINK_SECRET` distintos, `POSTGRES_HOST=localhost`,
   `POSTGRES_PORT=5432`, `JWT_ALGORITHM=HS256`,
   `JWT_ACCESS_EXPIRATION_MINUTES=60`,
   `JWT_REFRESH_EXPIRATION_DAYS=7`,
   `TELEGRAM_BOT_USERNAME=dosisalerta_bot`,
   `VITE_API_URL=http://localhost:8000/api/v1`.
   Dejar `TELEGRAM_BOT_TOKEN` vacío hasta tener el token de BotFather.
4. Verificar que `.env` está en `.gitignore` y no se sube a Git.
5. Validar con `docker compose config --quiet`.
6. Iniciar solo PostgreSQL con `docker compose up -d postgres`
   (en una terminal interactiva la primera vez, ver el problema
   conocido de arriba).
7. Comprobar con `pg_isready` y las consultas SQL de la sección 5.
8. La Fase 2 ya está autorizada y completada (migración
   `f2a17166bccd`, 13 tablas). La tabla 14
   `caregiver_link_attempts` NO se migra hasta la Fase 6.
