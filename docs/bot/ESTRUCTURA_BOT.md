# ESTRUCTURA DEL BOT DE TELEGRAM — DosisAlerta (demostración)

Esqueleto técnico inicial del bot, en modo **demostración con
datos ficticios**. No es la integración completa de la Fase 6:
deja la base organizada, modular y probada para continuar sin
adelantar ni alterar las demás fases.

Estado: 2026-11-11. Fases 1 y 2 completadas y publicadas en
GitHub (`5f75de0`). Fase 3 sin iniciar. Este esqueleto no
inicia ninguna fase: no toca PostgreSQL, ni JWT, ni modelos,
ni migraciones, ni el frontend.

## 1. Arquitectura

Dos procesos, un solo backend (acordado en Fase 0,
`docs/architecture/ARQUITECTURA.md` §2 y §5):

```text
Proceso API (Uvicorn, FastAPI, /api/v1)
  └─ Scheduler en el lifespan (Fase 5): único emisor de avisos

Proceso BOT (python -m app.bot.main, Fase 6)
  ├─ python-telegram-bot en polling (sin webhook en desarrollo)
  ├─ Handlers de comandos y botones
  └─ Llama a los MISMOS servicios que la web.
     Nunca accede directo a PostgreSQL.
```

En este esqueleto, los handlers usan datos ficticios
(`app.bot.services.mock_data`) porque los servicios centrales
todavía no existen. Cuando existan (Fases 3-5), los handlers
cambiarán la llamada al servicio y el resto de la estructura
seguirá igual.

Capas y su regla:

| Capa | Responsabilidad | Prohibido |
|---|---|---|
| `app/bot` | Traducir mensajes y botones a llamadas a servicios, y mostrar respuestas | Consultar PostgreSQL directamente |
| `app/services` | Toda la lógica de negocio | Hablar HTTP con Telegram |
| `app/models` | Tablas SQLAlchemy | Lógica de Telegram |

## 2. Estructura de archivos

```text
backend/app/bot/
├── __init__.py            # Documentación del paquete
├── main.py                # Punto de entrada (python -m app.bot.main)
├── config.py              # TELEGRAM_BOT_TOKEN y username desde .env
├── handlers/
│   ├── __init__.py        # register_handlers(application)
│   ├── start.py           # /start: bienvenida + menú principal
│   ├── menu.py            # Menú principal, texto libre, botón desconocido
│   ├── medications.py     # Mis medicamentos: lista y detalle
│   ├── treatments.py      # Mis tratamientos: lista y detalle
│   ├── reminders.py       # Próximas tomas (sin botones de registro)
│   ├── history.py         # Mi historial
│   ├── caregivers.py      # Mi familiar o cuidador
│   ├── settings.py        # Configuración
│   └── help.py            # Necesito ayuda + /help
├── keyboards/
│   ├── __init__.py
│   ├── main_menu.py       # Teclado principal (7 opciones)
│   └── navigation.py      # Botón "🏠 Menú principal"
├── services/
│   ├── __init__.py
│   └── mock_data.py       # Datos ficticios de demostración
└── tests/                 # (ver §6: las pruebas viven en app/tests/)

backend/app/tests/test_bot_structure.py   # 21 pruebas del bot
```

### Diferencias con la estructura objetivo del encargo

1. **Las pruebas no están en `backend/app/bot/tests/`.**
   Están en `backend/app/tests/test_bot_structure.py`, donde
   viven todas las pruebas del proyecto (Fase 1 y Fase 2).
   Motivo: `backend/pyproject.toml` fija
   `testpaths = ["app/tests"]`, así que `pytest` a secas
   recoge la suite completa sin tocar la configuración.
   Cambiar `testpaths` habría exigido modificar
   `pyproject.toml`, que está fuera del alcance autorizado.
2. **Dos módulos más que la lista objetivo:**
   `handlers/history.py` y `handlers/settings.py`. El menú
   aprobado tiene 7 secciones y la lista objetivo solo cubría
   5 handlers de sección; cada sección tiene su propio módulo
   (una responsabilidad por módulo), igual que las demás.
3. **`app/bot/__init__.py` actualizado.** Era el marcador
   reservado para la Fase 6; su docstring ahora describe el
   esqueleto de demostración. No se tocó ningún otro archivo
   existente.

## 3. Responsabilidad de cada módulo

### `main.py`

- Punto de entrada del proceso bot.
- `build_application(config)`: construye la aplicación de
  Telegram y registra los handlers. No conecta a la red, por
  eso se puede probar sin token real.
- `main()`: lee la configuración, exige el token (si falta, el
  proceso no arranca y explica por qué, sin mostrar el valor)
  y arranca el polling.
- `on_error`: registra el tipo de error sin tumbar el polling
  y sin registrar el token ni datos de salud.

### `config.py`

- `BotConfig.from_env()`: lee `TELEGRAM_BOT_TOKEN` (puede
  estar vacío en demostración) y `TELEGRAM_BOT_USERNAME`
  (por defecto `DosisAlertaBot`) desde variables de entorno o
  desde `.env` (busca el archivo hacia arriba desde el
  paquete, sin depender del directorio de trabajo).
- El campo `token` tiene `repr=False`: un `repr()` accidental
  nunca lo muestra. Los mensajes de error nunca incluyen el
  valor.
- Es independiente de `app.core.config` a propósito: el
  proceso bot debe poder arrancar y probarse sin la
  configuración de la API (sin PostgreSQL ni JWT).

### `handlers/`

Un módulo por sección del menú. Cada módulo separa la parte
pura (funciones `render_*` que devuelven texto y teclado, sin
Telegram) de la parte de Telegram (funciones `async` que
responden al callback o al comando). Así la navegación se
prueba sin conexión.

- `start.py`: `/start` → bienvenida + menú principal.
- `menu.py`: volver al menú (`menu:main`); cualquier texto
  escrito sin comando abre el menú; un botón desconocido
  (mensaje viejo) vuelve al menú con un mensaje amable.
- `medications.py`, `treatments.py`: lista ficticia con un
  botón "Ver ..." por elemento y pantalla de detalle.
- `reminders.py`: próximas tomas ficticias ordenadas por hora.
- `history.py`: historial ficticio (fecha, hora, origen).
- `caregivers.py`: cuidador ficticio y explicación de la
  función.
- `settings.py`: ajustes ficticios (zona horaria, avisos).
- `help.py`: ayuda de uso + comando `/help`. No da consejos
  de salud.

`handlers/__init__.py` (`register_handlers`) registra los
handlers en orden: primero los específicos, luego el de texto
libre y por último el de callbacks desconocidos.

### `keyboards/`

- `main_menu.py`: las 7 opciones del menú aprobado, un botón
  por fila. El `callback_data` lleva solo la sección
  (`menu:medications`, ...), siempre por debajo del límite de
  64 bytes de Telegram y sin datos sensibles.
- `navigation.py`: el botón "🏠 Menú principal"
  (`menu:main`) y el ayudante `with_home()` que lo añade al
  final de cualquier teclado. Toda pantalla que no sea el menú
  lo lleva; nunca hay callejones sin salida.

### `services/mock_data.py`

Datos ficticios, claramente identificados como demostración:

- 4 medicamentos, 2 tratamientos, 3 próximas tomas, 4
  entradas de historial y 1 cuidador de ejemplo.
- Todos los ids son texto que empieza por `demo-`; nunca se
  usan ids numéricos de base de datos.
- Cada pantalla que muestra estos datos incluye
  `DEMO_NOTICE` ("🔔 Modo demostración: los datos son
  ficticios y no se guarda nada.").
- Los valores de ejemplo siguen el formato de la
  especificación (`docs/ESPECIFICACION_BOT_TELEGRAM.md` §3.1);
  el paciente es ficticio.

## 4. Reglas de experiencia de usuario aplicadas

Para adultos mayores (especificación §1):

- Navegación solo con botones; ninguna función exige escribir
  comandos (`/start` es solo la puerta de entrada).
- Mensajes cortos, una idea por mensaje, horas en formato
  `08:00`.
- Pocas opciones por pantalla y siempre un botón para volver
  al menú principal.
- Los errores se explican en lenguaje normal ("No encontré
  ese medicamento"), nunca con trazas ni códigos internos.

**Tensión documentada (pendiente de decisión en Fase 6):**
la especificación propone "máximo 4 botones por mensaje en
el menú principal" (D-BOT-04, propuesta), pero el menú
aprobado tiene 7 opciones y las listas muestran un botón
"Ver ..." por elemento más el botón de inicio. Este esqueleto
prioriza mostrar las 7 secciones y el botón de inicio siempre
presente; en la Fase 6 habrá que decidir si el menú se
pagina (4 + 3) o si se mantiene en una sola pantalla.

## 5. Qué funciona y qué es simulado

**Funciona (demostración):**

- `/start` y `/help` responden con su pantalla.
- Las 7 secciones del menú navegan a su pantalla y vuelven
  al menú principal con el botón "🏠 Menú principal".
- Listas y detalles de medicamentos y tratamientos.
- Próximas tomas ordenadas por hora.
- Historial, cuidador, configuración y ayuda.
- Escribir texto libre abre el menú principal.
- Un botón desconocido no rompe el bot.
- Sin token, el proceso no arranca y lo explica.

**Simulado (no es funcionalidad real):**

- Todos los datos son ficticios (`mock_data`).
- No hay vinculación de cuentas ni de cuidadores.
- No hay creación, edición ni desactivación de medicamentos
  ni tratamientos.
- No hay confirmación ni posposición de tomas: la pantalla
  de próximas tomas **no incluye** los botones "✅ YA LO
  TOMÉ" ni "⏰ RECORDARME DESPUÉS" a propósito. Esos botones
  pertenecen a la experiencia futura de recordatorios y
  pulsarlos debe crear un registro real (Fases 5 y 6); en
  esta entrega solo se explica que aparecerán.
- No hay cambio de zona horaria ni silencio de avisos.
- No hay motor de recordatorios ni scheduler en el bot.
- El botón "NO LO HE TOMADO" no existe (eliminado
  definitivamente, 2026-11-11).

## 6. Cómo ejecutar la demostración

La demostración se prueba con la suite de pruebas: no hace
falta token real, ni PostgreSQL, ni conexión a Telegram.

```powershell
cd C:\Users\ASUS\Desktop\PROYECTO_ED2\DOSISALERTA\backend
.\.venv\Scripts\Activate.ps1
pytest app/tests/test_bot_structure.py -v   # solo el bot (21 pruebas)
pytest                                      # suite completa
```

Para arrancar el bot de verdad (polling) hace falta el token
real en `.env` (`TELEGRAM_BOT_TOKEN`, hoy vacío, pendiente
para la Fase 6) y la dependencia instalada (ver §7):

```powershell
python -m app.bot.main
```

Sin token, el proceso termina con:
`TELEGRAM_BOT_TOKEN no está configurado...`

## 7. Dependencias

**Versión declarada:** `python-telegram-bot==22.8`
(autorizada por el líder técnico el 2026-11-11; declarada en
la copia local, pendiente de transferir al PC).

- Es la última versión publicada en PyPI (consultada el
  2026-11-11). Exige Python >= 3.10 (el proyecto usa 3.12
  en desarrollo y 3.13.4 en el PC) y `httpx>=0.27,<0.29`,
  compatible con el `httpx==0.28.1` ya fijado en el proyecto.
- Declarada en `pyproject.toml` (`dependencies`), junto a las
  demás, con su comentario:

```toml
    # Preparacion del bot (demostracion): cliente de Telegram por polling.
    # Solo httpx como dependencia base; sin extras de la libreria.
    # Version autorizada por el lider tecnico el 2026-11-11.
    "python-telegram-bot==22.8",
```

- La librería está instalada solo en el entorno de validación
  local de esta entrega. En el PC del equipo hay que
  instalarla en `.venv` cuando se recupere la conexión, y
  después reinstalar con `pip install -e ".[dev]"` para que
  quede reproducible.
- No se actualizaron versiones existentes ni se instaló nada
  innecesario. Los extras de la librería (`job-queue`,
  `rate-limiter`, `callback-data`, etc.) no se usan.

## 8. Pruebas

`backend/app/tests/test_bot_structure.py` — 22 pruebas:

- Configuración: sin token no arranca; el token nunca aparece
  en `repr()`; username por defecto; un `.env` ajeno en el
  directorio de trabajo no tapa al del proyecto (regresión de
  la auditoría, ver §11).
- Teclados: el menú tiene las 7 opciones; todos los
  `callback_data` caben en 64 bytes; todas las pantallas
  llevan el botón de inicio.
- Datos ficticios: listas no vacías, ids `demo-`, próximas
  tomas ordenadas por hora, búsqueda por id.
- Handlers con objetos simulados: `/start`, menú, texto
  libre, botón desconocido, listas y detalles, historial,
  cuidador, configuración y ayuda; un id inventado responde
  sin excepción.
- **Sin registros reales:** la pantalla de próximas tomas no
  tiene botones de confirmación ni posposición (solo el de
  inicio); los botones futuros solo se explican en el texto.
- Registro de handlers: la aplicación se construye con un
  token falso (sin red) y registra 2 comandos, 10+ callbacks
  y 1 handler de texto.
- Separación: en un subproceso limpio, importar el bot no
  carga `sqlalchemy`, `asyncpg`, `psycopg` ni `app.models`,
  `app.database`, `app.services`, `app.repositories` o
  `app.scheduler`.

Resultados de la auditoría de integración (entorno de
validación local, Python 3.12.3, 2026-11-11):

- Bot: **22 pasadas** (21 iniciales + 1 de regresión de la
  auditoría, ver §11).
- Fase 1 (`test_config.py` + `test_health.py`): **12 pasadas**.
- Fase 2 (`test_models_fase2.py`, 31 pruebas): **1 pasada**
  (`test_no_confirm_permission_exists`, no necesita BD) y
  **30 errores de entorno** (el fixture no puede crear la BD
  de pruebas: no hay PostgreSQL en este entorno; todos con
  `OSError`, ninguno por fallo de código).
- Suite completa junta (`pytest`, 65 pruebas): **35 pasadas,
  30 errores, 0 fallidas**. Las 64 juntas (12 + 31 + 22) solo
  se pueden verificar en el PC, con PostgreSQL funcionando;
  según el informe del equipo, en el PC pasaron 64 por grupos
  separados, pero no juntas en una sola ejecución.

## 9. Integraciones pendientes (para la Fase 6)

1. Añadir el token real a `.env` (`TELEGRAM_BOT_TOKEN`).
2. Instalar `python-telegram-bot==22.8` en el `.venv` del PC
   (ya declarada en `pyproject.toml` en la copia local,
   autorizada el 2026-11-11; pendiente de transferir cuando
   se recupere la conexión).
3. Implementar la vinculación (`TelegramLinkService.confirm`,
   `POST /api/v1/telegram/link`, Fase 3) y el comando
   `/vincular`.
4. Conectar cada handler a los servicios centrales
   (medicamentos, tratamientos, horarios, recordatorios,
   historial — Fases 4 y 7) y sustituir `mock_data` por
   llamadas a servicios. El handler solo resuelve el usuario
   por `chat_id`, llama al servicio y formatea la respuesta.
5. Botones YA LO TOMÉ y RECORDARME DESPUÉS en los avisos
   del scheduler (Fase 5), con idempotencia (UNIQUE en
   `medication_intakes.reminder_id`).
6. Vinculación de cuidadores con código de un solo uso +
   aceptación explícita, 8 permisos, revocación y auditoría;
   migración de `caregiver_link_attempts` (tabla 14).
7. Rechazo de `chat_id` no vinculados (RF19) y validación
   de callbacks contra la BD.
8. Paginación de listas largas (5 en 5) y decisión sobre el
   máximo de 4 botones por pantalla (ver §4).

## 10. Contradicción detectada en la especificación oficial

`docs/ESPECIFICACION_BOT_TELEGRAM.md` está desactualizada en
dos puntos (no se modificó; se reporta para que el líder
técnico autorice su actualización):

1. **§0 y §9 dicen que la Fase 2 está "sin autorizar, sin
   iniciar".** La Fase 2 se completó y publicó el 2026-11-11
   (`5f75de0`, 13 tablas, migración `f2a17166bccd`, 43 pruebas
   en verde). La tabla de dependencias pendientes (§9) debe
   marcar la Fase 2 como completada.
2. **§9 dice que `python-telegram-bot` se fija "en la Fase
   6".** Este esqueleto de demostración ya propone la versión
   `22.8` (ver §7); la Fase 6 deberá confirmar esa versión o
   fijar otra.

## 11. Auditoría de integración (2026-11-11)

Auditoría final del esqueleto, ejecutada en el entorno de
validación local (el PC no era alcanzable por Tailscale/SSH).
Veredicto: **APROBADA CON OBSERVACIONES**. Correcciones
aplicadas en esta auditoría:

1. `backend/app/bot/config.py`: la búsqueda del `.env` ahora
   parte del archivo del paquete y sube por sus directorios
   padres, sin depender del directorio de trabajo. Antes, la
   primera opción era `find_dotenv` desde el cwd, que podía
   cargar un `.env` ajeno (lección de la Fase 2). Prueba de
   regresión en `test_bot_structure.py`.
2. `backend/alembic.ini`: `script_location = %(here)s/alembic`
   (antes, ruta relativa que solo funcionaba desde `backend/`).
   Ahora `alembic history` funciona también desde la raíz con
   `-c backend/alembic.ini`. La invocación habitual sigue
   siendo desde `backend/`.

Pendiente (requiere el PC): ejecutar la suite completa junta
(64 pruebas) con PostgreSQL, verificar `git diff --check`,
el estado de Git y de PostgreSQL, y la integridad de
`frontend/Q1.png` y `presentacion-trapecio-compuesto.pdf`.
También quedó desactualizado el ZIP de transferencia manual
(preparado antes de esta auditoría): hay que regenerarlo con
los archivos corregidos antes de pasarlo al PC.
