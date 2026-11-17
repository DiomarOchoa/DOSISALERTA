# docker/

Carpeta reservada para archivos de despliegue que se anadian en fases
posteriores (por ejemplo, un `Dockerfile` del backend en la Fase 9).

## PostgreSQL en desarrollo (Fase B)

El unico archivo de entorno es `../docker-compose.yml`, que define
solo PostgreSQL 17.11 para desarrollo local (imagen fijada en la
Fase A: `postgres:17.11-alpine`). El backend y el frontend **no**
se levantan con Docker: se ejecutan fuera, con `uvicorn` y con
`npm run dev`, para depurarlos con facilidad.

### Puesta en marcha (en un PC con Docker)

```powershell
# Windows PowerShell, desde la raiz del proyecto
Copy-Item .env.example .env
# Editar .env: poner una POSTGRES_PASSWORD de desarrollo
docker compose up -d postgres
docker compose ps
docker compose logs postgres
```

```bash
# Linux / macOS, desde la raiz del proyecto
cp .env.example .env
# Editar .env: poner una POSTGRES_PASSWORD de desarrollo
docker compose up -d postgres
docker compose ps
docker compose logs postgres
```

### Comprobacion de disponibilidad

```bash
docker compose exec postgres pg_isready -U dosisalerta -d dosisalerta
```

Si responde `accepting connections`, PostgreSQL esta listo. Si no,
revisar `docker compose logs postgres` antes de seguir con la Fase 2.

### Puerto configurable

El puerto del host es configurable con `POSTGRES_PORT` en `.env`
(5432 por defecto). El puerto dentro del contenedor siempre es
5432. Si el 5432 ya esta ocupado en el PC, basta cambiar
`POSTGRES_PORT` en `.env` sin tocar `docker-compose.yml`, y el
backend usara ese mismo valor (ver `backend/app/core/config.py`).

Antes de levantar el contenedor en un PC nuevo, comprobar que
puerto esta libre (Windows PowerShell, sin Docker):

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 5432 -InformationLevel Quiet
Test-NetConnection -ComputerName 127.0.0.1 -Port 5433 -InformationLevel Quiet
```

`True` significa ocupado; `False`, libre. Poner en `.env` el
primer puerto libre (5432, o 5433 si el 5432 esta ocupado, como
pasa en el PC del equipo, donde el 5432 lo ocupa un PostgreSQL 18
nativo). No asumir que todos los PC tienen la misma configuracion:
cada uno se comprueba por separado. Despues de levantar el
contenedor, verificar la version real con:

```bash
docker compose exec postgres psql -U dosisalerta -d dosisalerta -c 'SELECT version();'
```

Debe devolver PostgreSQL 17.11. Si devuelve otra version (por
ejemplo, 18), el contenedor no es el correcto o el puerto apunta
a otro servidor: detenerse y revisar antes de seguir.

### Persistencia

Los datos viven en el volumen `postgres-data`. Estos comandos
detienen el servicio **sin** borrar datos:

```bash
docker compose down
```

Este otro comando **si** borra el volumen y todos los datos de
prueba. Solo usarlo cuando se quiera empezar de cero:

```bash
docker compose down -v
```

### Verificacion (2026-11-11, PC del equipo)

PostgreSQL ya se ejecuto y se verifico en el PC del equipo: el
contenedor `dosisalerta-postgres` corre PostgreSQL 17.11,
publicado en el puerto 5433 del host (el 5432 lo ocupa el
PostgreSQL 18 nativo), con la migracion `f2a17166bccd` aplicada
(13 tablas) y `pg_isready` respondiendo `accepting connections`.
La primera ejecucion en cada PC nuevo debe repetirse y
registrarse con esa misma comprobacion (`pg_isready` y
`SELECT version();` = 17.11) antes de dar el entorno por
verificado en base de datos. No se declara que PostgreSQL
funciona sin esa comprobacion.

No se crea todavia ningun `Dockerfile` porque no hay modelos ni
migraciones que empaquetar en una imagen: crearlo ahora seria
inventar una imagen sobre un backend incompleto.
