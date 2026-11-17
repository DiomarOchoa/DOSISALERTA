# DosisAlerta — Guía de instalación en Windows (desde cero)

Guía completa para instalar y ejecutar DosisAlerta desde cero en un
computador Windows que nunca ha tenido el proyecto. Los cuatro
integrantes del equipo siguen exactamente los mismos pasos, con las
mismas versiones, para terminar con el mismo entorno reproducible.

> Alcance: entorno de desarrollo local para los 4 computadores del
> equipo. No incluye el bot de Telegram (Fase 6, sin publicar), ni
> autenticación JWT (Fase 3, sin iniciar), ni despliegue a
> producción. La Fase 3 sigue sin comenzar.

> Regla de oro de esta guía: **si un documento del repositorio dice
> algo distinto a esta guía, manda la guía.** Los README de backend
> y frontend todavía conservan pasos de la Fase 1 (por ejemplo,
> `pip install -e ".[dev]"`) que esta guía ya no usa: el flujo
> reproducible actual es el del lock de Python (pasos 11 y 12).

## 0. Antes de empezar: lee esto

- Todos los comandos se ejecutan en **Windows PowerShell**.
- Después de instalar una herramienta, **cierra y vuelve a abrir
  PowerShell** para que tome el nuevo `PATH`. Si un comando "no se
  reconoce", ese es casi siempre el motivo.
- No copies valores de ejemplo de otra persona: cada `.env` es
  propio de cada computador y **nunca** se sube a Git ni se comparte.
- Nunca ejecutes `docker compose down -v`: borra el volumen y
  todos los datos de PostgreSQL. Para detener, `docker compose
  down` (sin `-v`). Ver paso 19.
- Reserva aproximadamente una hora la primera vez; la mayor parte
  es descarga e instalación.

### Versiones canónicas (fijadas en la Fase A)

| Herramienta | Versión canónica | Cómo se fija en el repo |
|---|---|---|
| Python | **3.13.4** | `.python-version`, `requires-python >=3.12,<3.14` |
| Node.js | **24.12.0** | `.nvmrc`, `engines` en `frontend/package.json` |
| npm | **11.6.2** | `engines` + `engine-strict` en `frontend/.npmrc` |
| PostgreSQL | **17.11** | Imagen `postgres:17.11-alpine` en `docker-compose.yml` |
| Git | Reciente (sin pin) | — |
| Docker Desktop | Reciente, con Compose v2 | — |

Verificación final: `python --version` debe decir `Python 3.13.4`,
`node --version` debe decir `v24.12.0`, `npm --version` debe decir
`11.6.2`, y `SELECT version();` en PostgreSQL debe decir
`PostgreSQL 17.11`. Si alguna difiere, no sigas: corrígela primero.

### Requisitos de hardware y software

- Windows 10 de 64 bits (versión 2004 o superior) o Windows 11.
- Virtualización activada en la BIOS/UEFI (la necesita WSL2 y
  Docker Desktop; si Docker se queja de virtualización, se activa
  ahí, no en Windows).
- 8 GB de RAM como mínimo recomendado (Docker + navegador +
  editores a la vez).
- 10 GB libres en disco (Docker, imágenes, `node_modules`,
  entorno virtual).
- Conexión a internet (descargas de instaladores, imagen de
  PostgreSQL y paquetes).
- Cuenta de GitHub propia (ver paso 20) y permisos de
  administrador en tu computador para instalar programas.

---

## 1. Instalar Git

Git no viene en Windows. Instálalo por uno de estos dos caminos
(la versión exacta de Git no está fijada por el proyecto; vale
cualquier versión reciente):

**Opción A — con winget (recomendado):** en PowerShell como
administrador:

```powershell
winget install --id Git.Git -e
```

**Opción B — instalador oficial:** descarga Git para Windows desde
<https://git-scm.com/download/win> y sigue el instalador con las
opciones por defecto.

Cierra y reabre PowerShell y verifica:

```powershell
git --version
```

Configura Git con **tus propios datos** (nunca con los de otro
integrante):

```powershell
git config --global user.name "Tu Nombre"
git config --global user.email "tu-correo@ejemplo.com"
```

---

## 2. Instalar Python 3.13.4

La versión debe ser exactamente **3.13.4**. No instales 3.14 (el
proyecto lo excluye a propósito en `requires-python`) ni te quedes
con un 3.12 antiguo.

1. Descarga el instalador oficial (verificado, 64 bits):
   <https://www.python.org/ftp/python/3.13.4/python-3.13.4-amd64.exe>
2. Ejecútalo y marca la casilla **"Add python.exe to PATH"** antes
   de pulsar Install. Sin esa casilla, `python` no se reconocerá
   en PowerShell y tendrás que reinstalar.
3. Cierra y reabre PowerShell y verifica:

```powershell
python --version
```

Debe decir exactamente:

```text
Python 3.13.4
```

Si el computador ya tenía otro Python, comprueba cuál responde con
`where.exe python`. Si no es el 3.13.4, usa el lanzador `py`:

```powershell
py -3.13 --version
```

y en los pasos siguientes sustituye `python` por `py -3.13`
(solo en la creación del entorno virtual del paso 10).

---

## 3. Instalar Node.js 24.12.0 y npm 11.6.2

La versión debe ser exactamente **Node.js 24.12.0** (que trae
**npm 11.6.2**). El proyecto lo impone: `frontend/package.json`
tiene `engines` y `frontend/.npmrc` tiene `engine-strict=true`, así
que `npm ci` se negará a trabajar con otra versión.

1. Descarga el instalador oficial MSI (verificado, 64 bits):
   <https://nodejs.org/dist/v24.12.0/node-v24.12.0-x64.msi>
2. Ejecútalo con las opciones por defecto.
3. Cierra y reabre PowerShell y verifica:

```powershell
node --version
npm --version
```

Debe decir exactamente:

```text
v24.12.0
11.6.2
```

Si `npm` no se reconoce, cierra y reabre PowerShell (PATH). Si
`node --version` dice otra versión, desinstala esa versión desde
Configuración de Windows y vuelve a instalar la 24.12.0: no
intentes "arreglarlo" cambiando `engines` ni `.npmrc`.

---

## 4. Instalar Docker Desktop con WSL2

PostgreSQL corre en Docker; el backend y el frontend corren fuera
de Docker, directamente en Windows (ver `docker-compose.yml`: solo
define el servicio `postgres`).

1. Activa WSL2. En PowerShell **como administrador**:

```powershell
wsl --install
```

Si WSL2 ya estaba instalado, el comando lo dirá y no pasa nada.
Si te pide reiniciar, reinicia y sigue en el paso 2.

2. Descarga Docker Desktop (instalador oficial, versión reciente):
   <https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe>
3. Ejecútalo con las opciones por defecto (deja marcada "Use WSL 2
   instead of Hyper-V").
4. Abre Docker Desktop desde el menú Inicio y **espera a que el
   motor arranque** (el icono de la bandeja deja de animarse y dice
   "Engine running"). Docker Desktop debe estar abierto mientras
   trabajes con el proyecto.
5. Verifica en PowerShell:

```powershell
docker version
docker compose version
```

`docker version` debe mostrar cliente y servidor (si solo muestra
el cliente, el motor aún no arrancó: espera y reintenta).
`docker compose version` debe mostrar Compose v2.

> Problema conocido (verificado en el equipo): la **primera**
> descarga de la imagen de PostgreSQL debe hacerse en una terminal
> PowerShell **interactiva del propio PC**, no por SSH. El
> ayudante de credenciales de Docker Desktop necesita una sesión
> interactiva de Windows; por SSH la descarga falla con
> `error getting credentials - err: ... A specified logon session
> does not exist`. Una vez la imagen está en local, los siguientes
> arranques ya no necesitan descargar. Ver paso 9.

---

## 5. Clonar el repositorio

El repositorio es público, así que clonar no necesita
autenticación. Elige una carpeta de trabajo (por ejemplo,
`C:\Users\TU_USUARIO\Desktop\PROYECTO_ED2`, con tu propio usuario
de Windows) y clona:

```powershell
git clone https://github.com/DiomarOchoa/DOSISALERTA.git
cd DOSISALERTA
```

Comprueba que estás en la rama `main` y al día:

```powershell
git status
git log --oneline -3
```

El HEAD debe coincidir con el del resto del equipo (pregúntale al
responsable del proyecto cuál es el último commit antes de
empezar; en el PC del equipo era `5f75de0`, Fase 2 publicada).

> Para contribuir después (paso 20) necesitarás autenticación con
> **tu propia cuenta de GitHub** y una invitación como colaborador
> del repositorio. Para clonar no hace falta nada de eso.

---

## 6. Configurar el archivo raíz `.env`

El backend lee su configuración de un archivo `.env` en la **raíz
del proyecto**. Ese archivo **no existe** tras clonar (está en
`.gitignore`): se crea copiando la plantilla.

```powershell
Copy-Item .env.example .env
```

Abre `.env` con el Bloc de notas (clic derecho → Abrir con →
Bloc de notas, o `notepad .env` en PowerShell) y completa:

### Valores que sí debes poner (implementados)

| Variable | Qué poner |
|---|---|
| `POSTGRES_PASSWORD` | **Genera una contraseña nueva, solo para este PC.** En PowerShell: `python -c "import secrets; print(secrets.token_urlsafe(32))"`, copia el resultado y pégalo como valor. Nunca compartas ese valor ni lo subas a Git. |
| `POSTGRES_PORT` | El puerto que te salga libre en el paso 8 (5432 si está libre, 5433 si el 5432 está ocupado). **No lo pongas antes de hacer el paso 8.** |
| `POSTGRES_DB` | Déjalo como viene en la plantilla: `dosisalerta`. |
| `POSTGRES_USER` | Déjalo como viene en la plantilla: `dosisalerta`. |
| `POSTGRES_HOST` | Déjalo como viene en la plantilla: `localhost`. |
| `HOST` | Déjalo como viene: `127.0.0.1`. |
| `PORT` | Déjalo como viene: `8000`. |
| `DEBUG` | Déjalo como viene: `false`. |
| `CORS_ORIGINS` | Déjalo como viene: `http://localhost:5173`. |

### Variables reservadas: déjalas como vienen (no se leen todavía)

| Variable | Estado |
|---|---|
| `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_ACCESS_EXPIRATION_MINUTES`, `JWT_REFRESH_EXPIRATION_DAYS` | **Reservadas para la Fase 3 (autenticación), sin iniciar.** El backend no las lee todavía. Déjalas con los valores de la plantilla; no inventes secretos nuevos para ellas ni intentes activar el inicio de sesión. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_LINK_SECRET` | **Reservadas para la Fase 6 (bot de Telegram), sin publicar.** El bot no forma parte del entorno común. No crees ningún token en BotFather y no instales `python-telegram-bot`: no está en el lock de Python (paso 11) a propósito. |

### Lo que NO va en el `.env` raíz

- **`VITE_API_URL` no va aquí.** La plantilla raíz ya no la
  trae (Fase C). Vite solo lee variables desde la carpeta
  `frontend/`; la URL de la API se configura en `frontend/.env`
  (paso 7). Si tu `.env` raíz ya la tiene de una copia antigua,
  es una clave ignorada: no hace daño, pero no la uses.
- **No inventes variables de entorno.** Si una variable no está
  en `.env.example`, no la añadas: nada del código la leerá.
- **`DATABASE_URL` no existe en este proyecto.** No la crees: el
  backend construye la URL desde las cinco variables
  `POSTGRES_*`.

Guarda el archivo y verifica que `.env` está ignorado por Git (no
debe aparecer en `git status`):

```powershell
git status --short
```

Si `.env` aparece como archivo sin seguimiento, **detente**: no
hagas ningún commit hasta avisar al equipo (significa que
`.gitignore` no lo cubre en tu copia).

---

## 7. Configurar `frontend/.env`

El frontend (Vite) **solo** lee variables que empiezan por `VITE_`
y **solo** desde la carpeta `frontend/`. Su única variable es
`VITE_API_URL`, y su plantilla ya trae el valor correcto por
defecto:

```powershell
cd frontend
Copy-Item .env.example .env
cd ..
```

El valor es `http://localhost:8000/api/v1`. **No lo cambies** salvo
que hayas cambiado `PORT` en el `.env` raíz: si el backend escucha
en otro puerto, la URL debe apuntar a ese puerto con `/api/v1` al
final.

---

## 8. Detectar los puertos 5432 y 5433

Cada computador debe comprobar **sus propios puertos**: no asumas
que los cuatro tienen la misma configuración. El puerto 5432 puede
estar ocupado por un PostgreSQL nativo instalado en ese PC (en el
PC del equipo lo ocupa un PostgreSQL 18 nativo; en los demás puede
estar libre).

En PowerShell:

```powershell
Test-NetConnection -ComputerName localhost -Port 5432
Test-NetConnection -ComputerName localhost -Port 5433
```

- `TcpTestSucceeded : True` = **ocupado**.
- `TcpTestSucceeded : False` = **libre**.

Regla:

- Si el **5432 está libre**, pon `POSTGRES_PORT=5432` en el `.env`
  raíz (paso 6).
- Si el **5432 está ocupado**, pon `POSTGRES_PORT=5433` (o el
  primer puerto libre que encuentres probando en orden).
- El puerto **dentro** del contenedor es siempre 5432; lo que
  cambia es el puerto del host. No toques `docker-compose.yml`
  para cambiar el puerto: ese archivo ya prevé el cambio por
  variable de entorno.

La comprobación definitiva de que llegas al contenedor correcto
está en el paso 9: `SELECT version();` debe devolver
**PostgreSQL 17.11**. Si devuelve PostgreSQL 18 (u otra versión),
estás llegando al servidor nativo, no al contenedor: revisa
`POSTGRES_PORT`.

---

## 9. Iniciar PostgreSQL 17.11 con Docker Compose

Desde la raíz del proyecto, con Docker Desktop abierto:

```powershell
docker compose config --quiet
docker compose up -d postgres
docker compose ps
```

- `docker compose config --quiet` valida la configuración: debe
  salir sin error. Si falla, revisa tu `.env` (la causa más común
  es `POSTGRES_PASSWORD` vacío: Compose exige que esté definida).
- `docker compose up -d postgres` inicia **solo** PostgreSQL (el
  único servicio que define el proyecto).
- La primera vez descarga la imagen `postgres:17.11-alpine`
  (~117 MB). Hazlo en una terminal interactiva del propio PC (ver
  el problema conocido del paso 4).

Comprueba que el contenedor está sano:

```powershell
docker compose exec postgres pg_isready -U dosisalerta -d dosisalerta
docker compose exec postgres psql -U dosisalerta -d dosisalerta -c "SELECT version();"
```

Éxito: `pg_isready` responde `accepting connections` y
`SELECT version();` devuelve **PostgreSQL 17.11**. El contenedor
se llama `dosisalerta-postgres`, tiene `restart: unless-stopped`
(por eso vuelve solo al abrir Docker Desktop) y guarda los datos
en el volumen `postgres-data`.

---

## 10. Crear el entorno virtual de Python

El backend usa su propio entorno virtual, dentro de `backend/`:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

El prompt de PowerShell debe mostrar `(.venv)` al principio. Si
`Activate.ps1` da error de ejecución de scripts, es la política
de ejecución de Windows; se arregla una sola vez por usuario:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

y se vuelve a intentar la activación.

> El entorno virtual (`.venv`) no se sube a Git. Cada computador
> crea el suyo. No copies la carpeta `.venv` de otro computador.

---

## 11. Instalación reproducible con `requirements-lock.txt`

Con el entorno virtual activado y estando en `backend/`, instala
primero el lock (las versiones exactas, verificadas, de todas las
dependencias directas y transitivas):

```powershell
pip install -r requirements-lock.txt
```

El lock tiene 36 líneas y reproduce el entorno que pasó las 43
pruebas en el PC del equipo. Reglas del lock:

- **No edites `requirements-lock.txt` a mano.** Si una versión
  debe cambiar, es una decisión del equipo: se cambia en
  `pyproject.toml`, se reinstala en un entorno limpio, se pasan
  las pruebas y se regenera el lock con `pip freeze` (el
  procedimiento completo está en la cabecera del propio lock).
- El lock **no incluye `python-telegram-bot`**: el bot está fuera
  del entorno común hasta nueva autorización. No lo instales.
- Si `pip install -r requirements-lock.txt` falla por red, revisa
  la conexión y reintenta; no sustituyas el lock por un
  `pip install` libre.

---

## 12. Instalar el proyecto con `pip install -e . --no-deps`

Con el entorno virtual activado y estando en `backend/`:

```powershell
pip install -e . --no-deps
```

Esto instala el propio proyecto DosisAlerta en modo editable, sin
volver a resolver dependencias (`--no-deps`: las dependencias ya
están instaladas desde el lock). Así `uvicorn app.main:app`
encuentra el paquete `app`.

> No uses `pip install -e ".[dev]"` para este paso: ese es el
> comando antiguo de la Fase 1 y no reproduce el entorno fijado
> por el lock. La guía manda sobre los README antiguos en este
> punto (ver nota al inicio).

---

## 13. Aplicar las migraciones existentes

Con el entorno virtual activado, estando en `backend/` y con
PostgreSQL en marcha (paso 9):

```powershell
alembic upgrade head
alembic current
```

- `alembic upgrade head` aplica la migración inicial
  `f2a17166bccd`, que crea las 13 tablas de la Fase 2 en la base
  `dosisalerta`.
- `alembic current` debe mostrar `f2a17166bccd (head)`.

Comprueba las tablas creadas:

```powershell
docker compose exec postgres psql -U dosisalerta -d dosisalerta -c "\dt public.*"
```

Deben aparecer las 13 tablas de la Fase 2 más `alembic_version`
(14 tablas en el esquema `public`).

Reglas de migraciones:

- **No crees ni edites migraciones** sin autorización del equipo:
  el esquema se cambia con una migración nueva, revisada, nunca
  editando la migración ya aplicada.
- **No ejecutes `alembic downgrade`** en el entorno de
  desarrollo: borra tablas y datos.
- `ALEMBIC_DATABASE_URL` es un override **solo para pruebas**:
  las pruebas lo ponen y lo quitan ellas mismas (paso 17). Nunca
  lo definas en tu `.env` ni lo uses para apuntar Alembic a otra
  base de desarrollo.

---

## 14. Instalar el frontend con `npm ci`

Desde la carpeta `frontend/`:

```powershell
cd ..\frontend
npm ci
```

- Usa **`npm ci`, nunca `npm install` como procedimiento
  normal.** `npm ci` instala exactamente lo que fija
  `package-lock.json`; `npm install` puede actualizar el bloqueo
  y romper la reproducibilidad entre los cuatro computadores.
- `npm ci` borra `node_modules` y lo reinstala: es normal y no
  afecta al repositorio (`node_modules` está en `.gitignore`).
- Debe terminar con `added 69 packages` y `found 0
  vulnerabilities` (el número exacto de paquetes puede variar si
  el lock cambia en el futuro; lo que no debe aparecer es un
  error).

Comprobación opcional pero recomendada, la compilación:

```powershell
npm run build
```

Debe terminar sin errores (`tsc` en modo estricto y `vite build`
correctos). Si `tsc` falla, hay un error de tipos real: no lo
ignores ni lo "arregles" tocando la configuración de TypeScript.

---

## 15. Iniciar el backend y el frontend

Necesitas **dos terminales PowerShell** (o dos pestañas), con el
proyecto como carpeta de trabajo.

**Terminal 1 — backend** (entorno virtual activado, en `backend/`):

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

La API queda en <http://localhost:8000> y su documentación
automática en <http://localhost:8000/docs>. `--reload` reinicia el
servidor al guardar cambios en el código.

**Terminal 2 — frontend** (en `frontend/`):

```powershell
cd frontend
npm run dev
```

La web queda en <http://localhost:5173>.

> El backend debe arrancarse desde `backend/` porque su
> configuración busca el `.env` subiendo carpetas desde el
> directorio de trabajo. Si lo arrancas desde otra carpeta, puede
> cargar un `.env` distinto o ninguno. Lo mismo vale para
> `alembic` y `pytest`: siempre desde `backend/`.

---

## 16. Verificación de conectividad

Con backend y frontend en marcha:

1. En el navegador, abre <http://localhost:8000/health>. Debe
   responder:

```json
{"status": "ok", "app": "DosisAlerta", "version": "0.1.0"}
```

Lo mismo debe responder <http://localhost:8000/api/v1/health>.

2. Abre <http://localhost:5173>. La pantalla inicial muestra
   "DosisAlerta" y la URL de la API configurada. Pulsa
   **"Comprobar backend"**: debe decir "Backend en línea".

Si el botón dice que no puede contactar al backend, revisa en
este orden: que el backend esté en marcha en la terminal 1, que
escuche en el puerto 8000, y que `VITE_API_URL` en
`frontend/.env` apunte a `http://localhost:8000/api/v1`.

---

## 17. Ejecución segura de pruebas con base de datos aislada

Las pruebas se ejecutan desde `backend/`, con el entorno virtual
activado y PostgreSQL en marcha:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest
```

Resultado esperado: **43 passed** (12 de la Fase 1 + 31 de la
Fase 2). No debe haber fallos ni errores.

**Cómo está garantizado el aislamiento (no tienes que hacer
nada):**

- Las pruebas de modelos usan una base de datos de pruebas
  aparte, `dosisalerta_test`, que la propia sesión de pruebas
  crea vacía y migra con Alembic.
- La sesión de pruebas pone `ALEMBIC_DATABASE_URL` apuntando a
  esa base y la quita al terminar: nunca la definas a mano.
- Cada prueba corre dentro de una transacción que se revierte al
  final. La base de desarrollo (`dosisalerta`) **no recibe filas
  de prueba**.
- Las pruebas de la Fase 1 (salud y configuración) no tocan la
  base de datos.

**Reglas:**

- Nunca ejecutes las pruebas apuntando a la base de desarrollo:
  si ves `ALEMBIC_DATABASE_URL` definida en tu entorno o en tu
  `.env`, quítala antes de probar.
- No esperes 65 pruebas: las 22 del bot no están en el
  repositorio (el bot sigue sin publicar). 43 es el total
  correcto en este momento.
- Si una prueba falla, no la "arregles" editando la prueba ni la
  base de datos a mano: anota el fallo exacto y avisa al equipo.

---

## 18. Solución de errores frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `python` no se reconoce | Falta "Add python.exe to PATH" o terminal sin reabrir | Reinstala Python marcando la casilla; cierra y reabre PowerShell |
| `python --version` dice otra versión | Otro Python en el PATH | Usa `py -3.13` (paso 2) |
| `npm ci` falla con `EBADENGINE` | Versión de Node/npm distinta a la canónica | Instala Node.js 24.12.0 (paso 3); no toques `engines` ni `.npmrc` |
| `npm ci` dice que el lock no satisface `package.json` | Bloqueo desincronizado | No lo arregles con `npm install`: avisa al equipo, es un cambio a revisar |
| `Activate.ps1` bloqueado | Política de ejecución de Windows | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (paso 10) |
| `docker` dice que el demonio no está | Docker Desktop cerrado o motor sin arrancar | Abre Docker Desktop y espera a "Engine running" (paso 4) |
| La descarga de la imagen falla con `error getting credentials` | Descarga por SSH o sin sesión interactiva | Haz la primera descarga en una terminal interactiva del propio PC (pasos 4 y 9) |
| `docker compose config` falla | `.env` incompleto | Revisa que `POSTGRES_PASSWORD` esté definida y no vacía (paso 6) |
| `SELECT version();` devuelve PostgreSQL 18 | Estás llegando al servidor nativo, no al contenedor | Revisa `POSTGRES_PORT` en `.env` y repite la detección de puertos (paso 8) |
| `pg_isready` no responde | El contenedor no arrancó | `docker compose logs postgres` antes de tocar nada (paso 9) |
| `uvicorn` dice que el puerto 8000 está en uso | Otro backend ya corre | Para el proceso anterior (Ctrl+C en su terminal) y reintenta |
| El botón "Comprobar backend" falla | Backend parado o URL mal configurada | Revisa la terminal 1 y `VITE_API_URL` en `frontend/.env` (pasos 15 y 16) |
| Error CORS en el navegador | El frontend no corre en el puerto esperado | El CORS del backend solo admite `http://localhost:5173`: arranca el frontend con `npm run dev` sin cambiar el puerto |
| `pytest` falla por conexión a PostgreSQL | Contenedor parado o `POSTGRES_PORT` incorrecto | Arranca el contenedor (paso 9) y verifica `SELECT version();` |
| `alembic` dice que no encuentra la revisión | No estás en `backend/` o falta `.env` | Ejecuta siempre desde `backend/`, con el entorno activado (paso 13) |

Si un error no está en esta tabla, copia el mensaje **completo**
de la terminal y compártelo con el equipo antes de probar
soluciones de internet: un comando copiado a ciegas puede borrar
datos o romper el entorno.

---

## 19. Detener los servicios sin eliminar los datos

1. En la terminal del backend: **Ctrl+C**.
2. En la terminal del frontend: **Ctrl+C**.
3. Desde la raíz del proyecto, detén PostgreSQL:

```powershell
docker compose down
```

`docker compose down` detiene el contenedor **sin borrar el
volumen** `postgres-data`: los datos, las tablas y las migraciones
aplicadas siguen ahí al volver a arrancar.

**Nunca** ejecutes `docker compose down -v` como procedimiento
habitual: `-v` borra el volumen y **todos los datos**. Solo se
usa si el equipo decide, explícitamente y con copia de seguridad,
destruir y recrear la base desde cero.

Para volver a trabajar: abre Docker Desktop, y desde la raíz:

```powershell
docker compose up -d postgres
```

El contenedor arranca solo con `restart: unless-stopped` cuando
Docker Desktop abre, así que en muchos casos bastará con abrir
Docker Desktop y comprobar con `docker compose ps`.

---

## 20. Colaboración de los cuatro integrantes

### Cuentas y repositorio

- Cada integrante usa **su propia cuenta de GitHub** y su propio
  computador. Nadie trabaja con la cuenta ni con el computador de
  otro.
- El responsable del proyecto (Diomar) invita a cada integrante
  como colaborador del repositorio
  <https://github.com/DiomarOchoa/DOSISALERTA>. Sin esa invitación
  no se puede subir nada; clonar sí se puede, porque el
  repositorio es público.
- Cada integrante clona el repositorio en su computador (paso 5)
  y configura Git con su nombre y su correo (paso 1).

### Ramas y Pull Requests

- **Nadie trabaja directamente sobre `main`.** Cada tarea se hace
  en su propia rama, por ejemplo `feature/nombre-de-la-tarea` o
  `tu-nombre/nombre-de-la-tarea`.
- Cada commit es un **cambio real y atribuible**: un cambio por
  commit, con mensaje descriptivo (`feat:`, `fix:`, `docs:`,
  `test:`, `build:`, `refactor:`, `style:`). **No hay una cuota
  arbitraria de commits por integrante**: importan la calidad y
  la trazabilidad del trabajo, no el número.
- Cada integrante sube **su propia rama** con su cuenta
  (`git push origin nombre-de-la-rama`) y abre un **Pull Request
  hacia `main`**.
- **Ningún cambio se fusiona sin revisión.** Otro integrante (o
  el responsable del proyecto) revisa el Pull Request antes de
  fusionarlo. `main` se mantiene siempre en un estado que compila
  y pasa las pruebas.
- Si un Pull Request cambia el entorno (versiones, lock,
  `docker-compose.yml`, variables de entorno), debe decirlo
  explícito en su descripción y actualizar esta guía si el
  procedimiento cambia.

### Prohibido

- Compartir contraseñas, tokens, secretos de `.env` o cuentas de
  GitHub.
- Subir `.env` a Git (está en `.gitignore`; si aparece en
  `git status`, detenerse y avisar).
- Inventar autores: nunca hacer commits a nombre de otra persona
  ni atribuir trabajo que no se realizó.
- Hacer commits desde el computador o la cuenta de otro
  integrante.
- Modificar el esquema de PostgreSQL a mano en la base de datos:
  los cambios de esquema van por migraciones de Alembic,
  revisadas en Pull Request.
- Integrar el bot de Telegram o la autenticación JWT por cuenta
  propia: son fases sin autorizar (Fase 6 y Fase 3).

---

## Checklist final: ¿mi entorno está listo?

Marca cada punto antes de dar tu entorno por bueno:

- [ ] `python --version` → `Python 3.13.4`
- [ ] `node --version` → `v24.12.0` y `npm --version` → `11.6.2`
- [ ] `docker compose exec postgres pg_isready -U dosisalerta -d dosisalerta` → `accepting connections`
- [ ] `SELECT version();` → `PostgreSQL 17.11`
- [ ] `alembic current` → `f2a17166bccd (head)`
- [ ] `http://localhost:8000/health` → `{"status": "ok", ...}`
- [ ] `http://localhost:5173` → pantalla inicial y "Comprobar backend" en línea
- [ ] `pytest` (desde `backend/`) → `43 passed`
- [ ] `npm run build` (desde `frontend/`) → sin errores
- [ ] `git status` limpio de archivos que no deben subirse (`.env`,
      `.venv`, `node_modules`, `dist` no aparecen)

Si todo está marcado, tu computador está listo para trabajar en
DosisAlerta con el mismo entorno que los otros tres.

---

## Documentos relacionados

- `README.md` — presentación del proyecto y estado por fases.
- `docs/ENTORNO_LOCAL.md` — registro del entorno verificado en el
  PC del equipo (2026-11-11), con los problemas conocidos de ese
  PC (PostgreSQL 18 nativo en el 5432, descarga de imagen por
  terminal interactiva).
- `docker/README.md` — PostgreSQL en desarrollo y detección de
  puertos.
- `backend/README.md` y `frontend/README.md` — detalles de cada
  parte. Si contradicen esta guía en el procedimiento de
  instalación, manda esta guía. La alineación de esos README con
  esta guía ya fue realizada en el árbol de trabajo local
  (2026-11-17); su publicación es el commit 7 del plan de
  publicación por grupos.
- `.env.example` y `frontend/.env.example` — plantillas de
  variables, con las variables implementadas y reservadas
  diferenciadas.
- `backend/requirements-lock.txt` — lock de Python y su
  procedimiento de mantenimiento (en su cabecera).
