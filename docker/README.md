# docker/

Carpeta reservada para archivos de despliegue que se anadian en fases
posteriores (por ejemplo, un `Dockerfile` del backend en la Fase 9).

## PostgreSQL en desarrollo (Fase 1)

En la Fase 1, el unico archivo de entorno es `../docker-compose.yml`,
que define solo PostgreSQL 17 para desarrollo local. El backend y el
frontend **no** se levantan con Docker en esta fase: se ejecutan
fuera, con `uvicorn` y con `npm run dev`, para depurarlos con
facilidad.

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

### Limitacion honesta de la Fase 1

**PostgreSQL NO se ejecuto en el entorno donde se escribio la
Fase 1, porque ahi no hay Docker instalado.** La sintaxis del
archivo `docker-compose.yml` si se valido (YAML valido, servicio
`postgres`, imagen `postgres:17-alpine`, volumen `postgres-data`),
pero eso no es lo mismo que haber levantado el servicio. La primera
ejecucion real, con su salida de `pg_isready`, debe hacerse y
registrarse en el PC del equipo, donde si haya Docker, antes de dar
la Fase 1 por verificada en base de datos. No se declara que
PostgreSQL funciona sin esa comprobacion.

No se crea todavia ningun `Dockerfile` porque en la Fase 1 no hay
modelos ni migraciones que empaquetar: crearlo ahora seria inventar
una imagen sobre un backend incompleto.
