# ARQUITECTURA — DosisAlerta

Fase 0. Este documento es la referencia: si otro documento lo
contradice, este manda y la contradicción se corrige, no se convive
con ella.

## 1. Idea en una frase

**Un monolito modular en Python (FastAPI), con dos procesos que
comparten el mismo código, los mismos servicios y la misma base de
datos PostgreSQL, y dos canales de acceso: web React y bot de Telegram.**

No hay microservicios, no hay una base de datos por canal y no hay
lógica de negocio duplicada en el frontend ni en el bot.

## 2. Componentes y responsabilidades

| Componente | Responsabilidad | Lo que NUNCA hace |
|---|---|---|
| Frontend React | Presentar datos, recoger formularios, llamar a la API con JWT | Decidir reglas (dosis, horarios, estadísticas) |
| API FastAPI (`/api/v1`) | Recibir HTTP, validar con Pydantic, llamar a servicios, devolver JSON | Acceder a tablas sin pasar por repositorios |
| Servicios (`app/services`) | Toda la lógica de negocio, por dominio: usuarios, medicamentos, tratamientos, horarios, recordatorios, tomas, estadísticas, vinculación | Hablar HTTP con Telegram ni renderizar HTML |
| Repositorios (`app/repositories`) | Consultas a PostgreSQL, siempre filtradas por `user_id` | Validar reglas de negocio |
| Modelos (`app/models`) | Tablas SQLAlchemy, relaciones y restricciones | Contener lógica de envío o de Telegram |
| Esquemas (`app/schemas`) | Contratos Pydantic de entrada y salida | Tocar la base de datos |
| Bot de Telegram (`app/bot`) | Traducir mensajes y botones a llamadas a servicios, y mostrar respuestas | Consultar PostgreSQL directamente |
| Scheduler (`app/scheduler`) | Despertar a la hora de cada recordatorio, reclamarlo y enviarlo | Inventar recordatorios: solo lee los que ya existen en BD |
| Algoritmos (`app/algorithms`) | Cola de prioridad propia y estructuras del motor | Guardar estado: el estado vive en BD |
| PostgreSQL | Única fuente de verdad | — |

## 3. Los dos procesos (por qué dos, si es un monolito)

"Monolito modular" describe el **código**, no el número de procesos
en ejecución. El código es uno solo; al ejecutarlo se levantan dos
procesos porque hacen trabajos distintos y con ciclos de vida distintos:

```text
Proceso API
  uvicorn app.main:app --port 8000
  ├─ Routers REST /api/v1
  ├─ Servicios + repositorios + PostgreSQL
  └─ Scheduler (tarea asyncio en el lifespan): envía avisos por Telegram

Proceso BOT
  python -m app.bot.main
  ├─ python-telegram-bot en polling
  ├─ Handlers (comandos y botones)
  └─ Servicios + repositorios + PostgreSQL  (los mismos)
```

Ventajas de esta separación, sin romper el monolito:

- Si el bot se cae, la web sigue funcionando y el scheduler sigue
  enviando avisos; si la API se cae, el bot puede seguir respondiendo
  consultas (los avisos programados se recuperan al volver, ver §7).
- El bot no necesita un servidor HTTP público para recibir mensajes
  (polling), y la API no necesita saber nada del protocolo de Telegram.
- En la sustentación se puede demostrar cada proceso por separado y
  luego juntos, sin montar infraestructura de microservicios.

Regla de oro: **un proceso nunca escribe en una tabla que el otro no
pueda leer con el mismo servicio.** Si una operación solo existe en el
bot y no en el servicio, es un error de diseño y se corrige antes de
seguir.

## 4. Flujo de una petición web

```text
Usuario → React → POST /api/v1/treatments (JWT)
  → Router: valida el esquema Pydantic
  → Dependencia: usuario actual a partir del JWT + sesión async de BD
  → Servicio (TreatmentService): verifica propiedad, reglas y horarios
  → Repositorio: INSERT/UPDATE en PostgreSQL, en una transacción
  → Respuesta JSON (esquema de salida, nunca el modelo interno)
```

Errores con formato único (Fase 3, ya decidido):

```json
{"detail": "El tratamiento no pertenece al usuario actual", "code": "FORBIDDEN"}
```

Códigos: `400` datos inválidos, `401` sin token o expirado, `403`
recurso de otro usuario, `404` no existe, `409` conflicto (por
ejemplo, un horario que se solapa de forma inválida), `500` error
interno sin filtrar detalles técnicos al cliente.

## 5. Comunicación bidireccional web ↔ Telegram

Esta es la parte que más se evalúa y la que más se rompe si se
improvisa. El mecanismo es siempre el mismo, en ambas direcciones:
**el canal que origina el cambio llama a un servicio; el servicio
escribe en PostgreSQL; el otro canal, al consultar, ve el cambio
porque lee la misma base de datos.** No hay sincronización, no hay
colas entre canales y no hay copias de datos.

### 5.1. Vinculación de cuentas (el puente)

1. Web (con sesión): `POST /api/v1/telegram/link` → el servicio genera
   un código de un solo uso (10 caracteres, alfabeto sin confusiones,
   con `secrets`, expira en 15 minutos) y crea una fila en
   `telegram_accounts` en estado `PENDIENTE`, guardando solo su
   HMAC-SHA256 con el secreto dedicado `TELEGRAM_LINK_SECRET`.
2. Usuario en Telegram: `/vincular ABC12345` (ejemplo de formato, no
   un código real).
3. El handler del bot llama a `TelegramLinkService.confirm(code,
   telegram_user_id, chat_id)`: compara con `hmac.compare_digest`,
   valida vencimiento y límite de intentos (ver §6 y
   `MODELO_DATOS.md` §7.3), y marca la fila como `VINCULADA` con
   `chat_id` y `telegram_user_id`, borrando el hash del código en la
   misma transacción.
4. La web, al recargar Ajustes, consulta el mismo servicio y muestra
   "Telegram vinculado". El código ya usado no se puede reutilizar, y
   un código inexistente, vencido, usado o bloqueado devuelve el
   mismo mensaje genérico, para no revelar qué códigos existen.
5. Desvincular desde la web marca la fila como `REVOCADA`: el scheduler
   deja de enviar a ese `chat_id` y el bot deja de responder órdenes
   de ese usuario hasta una nueva vinculación.

### 5.2. Web → Telegram (un cambio en la web llega a Telegram)

Ejemplo: el usuario crea un tratamiento en la web.

1. `TreatmentService.create` guarda tratamiento, vínculo con
   medicamentos y horarios, en una transacción.
2. `ReminderGenerator` crea las ocurrencias de los próximos 7 días
   (ver §7 y `MODELO_DATOS.md`).
3. El scheduler, que ya está corriendo, carga esas ocurrencias en su
   cola de prioridad en el siguiente ciclo de recarga.
4. A la hora programada, el scheduler reclama el recordatorio y lo
   envía con `Bot.send_message(chat_id, texto, botones)`, guardando el
   `telegram_message_id` en `notification_logs`.
5. El usuario ve el aviso en Telegram sin haber hecho nada en Telegram.

Ejemplo inverso en el mismo sentido: si el usuario cancela el
tratamiento en la web, el servicio marca sus recordatorios pendientes
como `CANCELADA` y los invalida en la cola; Telegram simplemente no
los enviará. No hay que "avisar" a Telegram: basta con no enviar.

### 5.3. Telegram → Web (un cambio en Telegram llega a la web)

Ejemplo: el usuario pulsa **Tomada** en un aviso de Telegram.

1. El botón lleva un `callback_data` con el `reminder_id` (nunca con
   datos sensibles ni con el `user_id` en texto plano innecesario).
2. El handler del bot resuelve el usuario a partir del `chat_id`
   vinculado y llama a `IntakeService.confirm(reminder_id, source=TELEGRAM)`.
3. El servicio, en una transacción: verifica que el recordatorio
   pertenece a ese usuario, que sigue en estado enviable, crea la fila
   en `medication_intakes` y marca el recordatorio como `TOMADA`.
4. El bot edita el mensaje ("✓ Tomada a las 08:02") para que no se
   pueda pulsar dos veces con efecto.
5. La web, al abrir Historial o Estadísticas, consulta los mismos
   servicios y muestra la toma, su hora y su origen (Telegram).

Lo mismo aplica a **Posponer** (crea un nuevo recordatorio hijo y
marca el anterior como `POSPUESTA`), **Cancelar tratamiento** y
**Crear medicamento** desde el bot: siempre el mismo servicio que
usaría la web, siempre la misma transacción, siempre la misma BD.

### 5.4. Qué garantiza que no se desincronicen

- **Propiedad en el servicio, no en el canal:** toda consulta filtra
  por `user_id` del usuario autenticado (web) o vinculado (bot). Un
  `reminder_id` adivinado de otro usuario devuelve `403`, no datos.
  Antes de crear un hijo, el servicio comprueba que el padre es del
  mismo usuario (ver checklist en `MODELO_DATOS.md` §7.2).
- **Red de seguridad en la BD:** `user_id` desnormalizado en las
  tablas hijas y FK compuestas `(padre_id, user_id)`. Una FK simple
  solo comprueba existencia; la compuesta impide en la transacción
  mezclar el tratamiento de un usuario con el medicamento de otro,
  aunque el servicio tuviera un error.
- **Una transacción por operación:** o se guarda la toma y se cambia
  el estado del recordatorio, o no se guarda nada.
- **El estado vive en BD, no en memoria del bot ni del frontend:** si
  el bot reinicia, no pierde tomas; si la web se recarga, no pierde
  horarios.
- **El scheduler es el único emisor de avisos:** el bot nunca envía
  recordatorios por su cuenta fuera del scheduler, así que un aviso no
  puede salir dos veces por dos caminos distintos (ver §7).

## 6. Seguridad (resumen; detalle en Fase 3)

- Contraseñas con bcrypt, nunca en texto plano, nunca en logs.
- JWT: access de 60 minutos y refresh de 7 días, este último guardado
  con hash en `refresh_tokens` y revocable al cerrar sesión.
- Secreto JWT, secreto de códigos de vinculación
  (`TELEGRAM_LINK_SECRET`) y token de Telegram solo en `.env`
  (python-dotenv). Ninguno aparece en código, documentación, logs ni
  capturas de la sustentación.
- Códigos de vinculación: `secrets`, 10 caracteres, HMAC-SHA256,
  15 minutos, un solo uso, 5 fallos por `chat_id` en 15 minutos y
  5 fallos por código (luego se invalida), mensaje genérico ante
  cualquier fallo. Detalle en `MODELO_DATOS.md` §7.3.
- CORS restringido al origen del frontend en desarrollo
  (`http://localhost:5173`); en producción, al dominio real.
- El bot valida que cada `chat_id` esté vinculado antes de obedecer
  cualquier comando que toque datos.

## 7. Motor de recordatorios (resumen; diseño completo en la Fase 5 del roadmap y en DECISIONES)

- **Fuente de verdad:** la tabla `medication_reminders`.
- **Generación:** ocurrencias para los próximos 7 días, idempotentes
  por restricción única `(schedule_id, scheduled_at)`.
- **Orden:** cola de prioridad propia (`app/algorithms/ReminderHeap`,
  heap binario) ordenada por `scheduled_at` UTC; `heapq` como respaldo
  detrás de la misma interfaz.
- **Búsqueda rápida:** diccionarios `jobs_by_id` y `jobs_by_user`
  (hash map de Python) para cancelar o reprogramar en O(1) sin
  recorrer la cola.
- **Concurrencia:** una sola tarea scheduler en el proceso API,
  `asyncio.Lock` para la cola y la reclamación en BD como bloqueo
  real (una transacción `UPDATE ... WHERE status='PENDIENTE'` con un
  `current_attempt_id` nuevo por intento; solo quien reclama envía).
- **Recuperación y reconciliación:** al arrancar, se recargan los
  `PENDIENTE`; los `ENVIANDO` con más de 5 minutos se reconcilian,
  no se reenvían a ciegas (ver `MODELO_DATOS.md` §9). Los vencidos
  fuera de la ventana de gracia (30 min) se marcan `PERDIDA`.
- **Promesa realista (corrección):** Telegram Bot API no ofrece
  claves de idempotencia ni forma de verificar un envío, así que no
  se promete envío exactamente una vez. La garantía es: **entrega
  al menos una vez, efecto exactamente una vez** (una toma por
  recordatorio, botones idempotentes) **y ningún fallo silencioso**
  (todo intento queda en `notification_logs` con `attempted_at`,
  y `sent_at` solo cuando Telegram confirma). Un intento ambiguo
  (respuesta perdida) queda `AMBIGUA`, no se inventa como enviado,
  y se decide en reconciliación con un único reintento. En el peor
  caso, un aviso podría llegar duplicado; nunca debe crear dos tomas
  ni perderse sin registro.
- **Zonas horarias:** todo instante en UTC (`TIMESTAMPTZ`); las
  horas de horario son horas de pared y las fechas son fechas de
  calendario en la zona del usuario (`users.timezone`, IANA).
  Generación con `ZoneInfo`, con reglas para horas inexistentes
  (desplazar a la primera válida) y ambiguas (primera ocurrencia)
  en DST, y recálculo de los `PENDIENTE` futuros al cambiar de zona.
  Detalle en `MODELO_DATOS.md` §8.

## 8. Estándares de código (aplican desde la Fase 1)

- Funciones pequeñas, con un solo motivo para cambiar; nombres que
  dicen qué hacen (`confirm_intake`, no `do_action`).
- Docstrings en clases y funciones públicas importantes; comentarios
  solo donde el "por qué" no es obvio (algoritmos, reclamación,
  zonas horarias).
- Tipado con Pydantic en la frontera (API) y anotaciones de tipo en
  servicios y repositorios.
- Sin código muerto, sin duplicación entre web y bot (si algo se
  repite, va al servicio).
- Manejo de excepciones por capas: el repositorio no decide el mensaje
  al usuario; el servicio lanza excepciones de dominio y el router
  las traduce a HTTP.
- Pruebas antes de dar una fase por terminada (ver ROADMAP).

## 9. Lo que esta arquitectura NO promete (para no vender humo)

- No es multi-instancia: con dos procesos API corriendo a la vez, el
  scheduler duplicaría envíos. En esta versión hay una sola instancia
  API; escalar requeriría un bloqueo distribuido y queda fuera de alcance.
- No promete envío exactamente una vez por Telegram: la API no lo
  permite asegurar (ver §7 y `MODELO_DATOS.md` §9).
- No hay notificaciones push web ni WebSocket: la web recarga al
  entrar a cada vista. Es suficiente para los requisitos y evita una
  tecnología innecesaria.
- No hay modo offline ni app móvil: web + Telegram son los dos canales
  exigidos y los dos que se entregan.
