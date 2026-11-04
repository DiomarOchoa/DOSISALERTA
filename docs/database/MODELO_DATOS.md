# MODELO DE DATOS — DosisAlerta

Fase 0. PostgreSQL 17. Todas las claves primarias son `BIGINT`
autoincrementales. Todos los instantes son `TIMESTAMPTZ` en UTC.
Los enumerados se guardan como `VARCHAR` con `CHECK` (no como tipo
ENUM nativo de PostgreSQL) para que una migración futura no tenga que
alterar un tipo en toda la base.

Convenciones: tablas en plural y `snake_case`; `created_at` y
`updated_at` en todas las tablas de negocio; borrado lógico, no
`DELETE`, en tablas de negocio (ver §6).

## 1. Diagrama entidad-relación (resumen)

```text
users 1───* medications
users 1───* treatments
users 1───1 telegram_accounts
users 1───* refresh_tokens
users 1───* notification_logs (vía reminders, denormalizado por consulta)

treatments 1───* treatment_medications *───1 medications
treatment_medications 1───* medication_schedules
medication_schedules 1───* medication_reminders
medication_reminders 1───* medication_reminders (hijo por posposición)
medication_reminders 0───1 medication_intakes
medication_reminders 1───* notification_logs
telegram_link_attempts: sin FK a users (se registra por chat_id,
incluso para intentos de chats no vinculados; ver §3.11 y §7.3)
```

El diagrama Mermaid completo está en `docs/diagrams/DIAGRAMAS.md`.

## 2. Por qué existe la tabla intermedia treatment_medications

La pregunta que el diseño debía resolver era: ¿un tratamiento tiene
un medicamento, o varios, y el horario pertenece a quién?

- Un medicamento es un **catálogo propio del usuario** (por ejemplo,
  "Amoxicilina 500 mg"): existe aunque no esté en ningún tratamiento
  activo, y puede reutilizarse en otro tratamiento después.
- Un tratamiento es un **plan** (por ejemplo, "Tratamiento de 7 días
  de noviembre"): tiene inicio, fin y estado.
- La dosis no pertenece ni al catálogo ni al plan por sí sola: la
  misma amoxicilina puede tomarse 1 cápsula cada 8 horas en un
  tratamiento y 1 cada 12 horas en otro. Por eso la dosis, la
  frecuencia escrita y las instrucciones viven en
  `treatment_medications`.
- El horario tampoco pertenece al medicamento solo: el mismo
  medicamento en el mismo tratamiento puede tener un horario de
  mañana y otro de noche. Por eso `medication_schedules` cuelga de
  `treatment_medications`, no de `medications` ni de `treatments`.

Consecuencia práctica: cambiar la dosis de un tratamiento no cambia
el catálogo ni el historial de otro tratamiento anterior.

## 3. Tablas

### 3.1. users

| Columna | Tipo | Restricción |
|---|---|---|
| id | BIGINT | PK, autoincremental |
| name | VARCHAR(120) | NOT NULL |
| email | VARCHAR(255) | NOT NULL, UNIQUE |
| password_hash | VARCHAR(255) | NOT NULL (bcrypt, nunca texto plano) |
| timezone | VARCHAR(50) | NOT NULL, DEFAULT 'America/Bogota' (configurable) |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |

### 3.2. medications (catálogo propio del usuario)

| Columna | Tipo | Restricción |
|---|---|---|
| id | BIGINT | PK |
| user_id | BIGINT | NOT NULL, FK → users.id |
| name | VARCHAR(150) | NOT NULL |
| presentation | VARCHAR(100) | NULL (tableta, jarabe, cápsula…) |
| concentration | VARCHAR(50) | NULL (ej. "500 mg") |
| unit | VARCHAR(30) | NULL (ej. "tableta") |
| notes | TEXT | NULL |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL |

### 3.3. treatments

| Columna | Tipo | Restricción |
|---|---|---|
| id | BIGINT | PK |
| user_id | BIGINT | NOT NULL, FK → users.id |
| title | VARCHAR(150) | NOT NULL |
| notes | TEXT | NULL |
| start_date | DATE | NOT NULL |
| end_date | DATE | NULL, CHECK (end_date IS NULL OR end_date >= start_date) |
| status | VARCHAR(20) | NOT NULL, CHECK IN ('ACTIVO','PAUSADO','COMPLETADO','CANCELADO') |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL |

### 3.4. treatment_medications (tratamiento × medicamento)

| Columna | Tipo | Restricción |
|---|---|---|
| id | BIGINT | PK |
| user_id | BIGINT | NOT NULL, FK → users.id (desnormalizado; ver §7, integridad entre cuentas) |
| treatment_id | BIGINT | NOT NULL, FK compuesta (treatment_id, user_id) → treatments(id, user_id) |
| medication_id | BIGINT | NOT NULL, FK compuesta (medication_id, user_id) → medications(id, user_id) |
| dose_amount | NUMERIC(10,3) | NOT NULL, CHECK (dose_amount > 0) |
| dose_unit | VARCHAR(30) | NOT NULL |
| instructions | TEXT | NULL (ej. "con alimentos") |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL |

Para que la FK compuesta funcione, `treatments` y `medications`
llevan además UNIQUE `(id, user_id)` (la PK ya garantiza `id` único;
esta restricción adicional es la que permite referenciar el par).
Sin ella, una FK simple solo comprobaría que el tratamiento y el
medicamento existen, no que son del mismo usuario.

Restricción adicional: UNIQUE `(treatment_id, medication_id)` cuando
el vínculo está activo (en la práctica, se evita duplicar el mismo
medicamento activo dos veces en un tratamiento; si se necesita dos
dosis distintas, se usan dos horarios, no dos vínculos).

### 3.5. medication_schedules (recurrencia de un medicamento en un tratamiento)

| Columna | Tipo | Restricción |
|---|---|---|
| id | BIGINT | PK |
| user_id | BIGINT | NOT NULL, FK → users.id (desnormalizado; ver §7) |
| treatment_medication_id | BIGINT | NOT NULL, FK compuesta (treatment_medication_id, user_id) → treatment_medications(id, user_id) |
| frequency | VARCHAR(20) | NOT NULL, CHECK IN ('DIARIO','DIAS_SEMANA','INTERVALO_DIAS') |
| days_of_week | INTEGER[] | NULL: 0=lunes … 6=domingo, solo si frequency='DIAS_SEMANA' |
| interval_days | INTEGER | NULL, CHECK (interval_days IS NULL OR interval_days >= 1), solo si INTERVALO_DIAS |
| times | TIME[] | NOT NULL, al menos una hora (ej. 08:00, 20:00) |
| start_date | DATE | NOT NULL |
| end_date | DATE | NULL, CHECK (end_date IS NULL OR end_date >= start_date) |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL |

La hora se guarda como `TIME` local del usuario; el instante UTC
concreto se calcula al generar cada recordatorio con su zona horaria.

### 3.6. medication_reminders (cada toma programada, individual)

Esta es la tabla del motor. **Cada fila es una toma concreta, no un
horario genérico.** Sin esta tabla no se podría decir "esta toma se
perdió" ni "esta se pospuso".

| Columna | Tipo | Restricción |
|---|---|---|
| id | BIGINT | PK |
| schedule_id | BIGINT | NOT NULL, FK compuesta (schedule_id, user_id) → medication_schedules(id, user_id) |
| treatment_medication_id | BIGINT | NOT NULL, FK compuesta (treatment_medication_id, user_id) → treatment_medications(id, user_id) |
| user_id | BIGINT | NOT NULL, FK → users.id (desnormalizado para aislamiento por usuario) |
| scheduled_at | TIMESTAMPTZ | NOT NULL (instante UTC calculado; ver §8) |
| status | VARCHAR(20) | NOT NULL, CHECK IN ('PENDIENTE','ENVIANDO','ENVIADA','TOMADA','POSPUESTA','PERDIDA','CANCELADA','FALLIDA') |
| parent_reminder_id | BIGINT | NULL, FK → medication_reminders.id (el original, si este nació de posponer) |
| postponed_count | INTEGER | NOT NULL, DEFAULT 0 |
| version | INTEGER | NOT NULL, DEFAULT 1 (para la cola y la reclamación) |
| current_attempt_id | UUID | NULL (identifica la reclamación en curso; ver §9) |
| claimed_at | TIMESTAMPTZ | NULL (cuándo se reclamó el intento en curso) |
| next_attempt_at | TIMESTAMPTZ | NULL (reintento tras fallo claro de Telegram) |
| attempt_count | INTEGER | NOT NULL, DEFAULT 0 |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL |

Transiciones permitidas (el servicio las impone, no solo la BD):
`PENDIENTE → ENVIANDO → ENVIADA → TOMADA`;
`PENDIENTE → POSPUESTA` (crea hijo); `PENDIENTE/ENVIADA → PERDIDA`
(fuera de gracia); `ENVIANDO → PENDIENTE` solo en reconciliación
tras un fallo claro o un intento ambiguo agotado según §9;
cualquier pendiente → `CANCELADA` (al cancelar el tratamiento);
`ENVIANDO → FALLIDA` cuando se agotan los reintentos sin confirmación
de Telegram. No hay transición de vuelta desde `TOMADA`, `PERDIDA`
ni `FALLIDA` hacia un envío nuevo del mismo recordatorio: un
recordatorio fallido se muestra como tal en la web, no se reenvía
en silencio días después.

### 3.7. medication_intakes (la toma confirmada: historial)

| Columna | Tipo | Restricción |
|---|---|---|
| id | BIGINT | PK |
| reminder_id | BIGINT | NOT NULL, UNIQUE, FK compuesta (reminder_id, user_id) → medication_reminders(id, user_id) |
| user_id | BIGINT | NOT NULL, FK → users.id |
| taken_at | TIMESTAMPTZ | NOT NULL (cuándo se confirmó, en UTC) |
| source | VARCHAR(20) | NOT NULL, CHECK IN ('WEB','TELEGRAM') |
| note | TEXT | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |

¿Por qué `medication_intakes` y no solo el estado del recordatorio?
Porque el recordatorio dice **qué estaba programado** y la toma dice
**qué pasó realmente** (cuándo y desde dónde). Si mañana cambia el
tratamiento, la toma sigue intacta; si se borrara el recordatorio, se
perdería la historia. Por eso `reminder_id` es UNIQUE (una toma por
recordatorio) y nunca se borra.

### 3.8. telegram_accounts

| Columna | Tipo | Restricción |
|---|---|---|
| id | BIGINT | PK |
| user_id | BIGINT | NOT NULL, UNIQUE, FK → users.id (un vínculo por usuario en v1) |
| telegram_user_id | BIGINT | NULL hasta vincular, luego NOT NULL y UNIQUE |
| chat_id | BIGINT | NULL hasta vincular, luego NOT NULL |
| username | VARCHAR(100) | NULL |
| link_code_hash | VARCHAR(64) | NULL (solo mientras está PENDIENTE; ver §7.3) |
| link_expires_at | TIMESTAMPTZ | NULL |
| status | VARCHAR(20) | NOT NULL, CHECK IN ('PENDIENTE','VINCULADA','REVOCADA') |
| linked_at | TIMESTAMPTZ | NULL |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL |

El código en texto plano **nunca** se guarda, nunca se registra en
logs y nunca se devuelve por la API. Solo se guarda su HMAC-SHA256
(hex, 64 caracteres) calculado con un secreto dedicado en `.env`
(`TELEGRAM_LINK_SECRET`). Al vincular con éxito, o al expirar o
revocarse el código, `link_code_hash` y `link_expires_at` se ponen
a NULL: un código usado o vencido no debe quedar reutilizable ni
siquiera como hash. Detalle completo en §7.3 y en
`DECISIONES_TECNICAS.md` (D10 revisada).

### 3.9. refresh_tokens

| Columna | Tipo | Restricción |
|---|---|---|
| id | BIGINT | PK |
| user_id | BIGINT | NOT NULL, FK → users.id |
| token_hash | VARCHAR(255) | NOT NULL (hash del refresh, nunca el token) |
| expires_at | TIMESTAMPTZ | NOT NULL |
| revoked_at | TIMESTAMPTZ | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |

### 3.10. notification_logs (auditoría de envíos)

Corrección de la versión anterior: `sent_at` era NOT NULL, lo que
hacía imposible registrar un intento fallido. Ahora se separan
intento y confirmación.

| Columna | Tipo | Restricción |
|---|---|---|
| id | BIGINT | PK |
| reminder_id | BIGINT | NOT NULL, FK compuesta (reminder_id, user_id) → medication_reminders(id, user_id) |
| user_id | BIGINT | NOT NULL, FK → users.id |
| channel | VARCHAR(20) | NOT NULL, DEFAULT 'TELEGRAM' |
| attempt_id | UUID | NOT NULL (el mismo de `medication_reminders.current_attempt_id`) |
| attempted_at | TIMESTAMPTZ | NOT NULL (cuándo se intentó enviar, siempre se registra) |
| sent_at | TIMESTAMPTZ | NULL (solo cuando Telegram confirmó con `telegram_message_id`; NULL en FALLIDA y en AMBIGUA) |
| telegram_message_id | BIGINT | NULL (el id que devuelve Telegram; solo presente si `sent_at` no es NULL) |
| status | VARCHAR(20) | NOT NULL, CHECK IN ('ENVIADA','FALLIDA','AMBIGUA') |
| error | TEXT | NULL (mensaje de error de la API, o 'respuesta perdida tras el envío' en AMBIGUA; nunca el token) |

Reglas:

- Se crea **una fila por intento**, antes o inmediatamente después
  de llamar a Telegram, nunca solo si el envío salió bien. Un
  recordatorio con intentos fallidos debe ser visible en la auditoría.
- `ENVIADA` exige `sent_at` NOT NULL y `telegram_message_id` NOT NULL
  (restricción CHECK en la migración de la Fase 2).
- `FALLIDA` exige `sent_at` NULL: un fallo claro de la API (por
  ejemplo, chat no encontrado o bot bloqueado) no es un envío.
- `AMBIGUA` exige `sent_at` NULL y `telegram_message_id` NULL: el
  envío pudo haber llegado, pero la respuesta se perdió (caída de
  red, timeout tras enviar). Es el caso que impide prometer
  "exactamente una vez" en Telegram (ver §9): la reconciliación
  decide, no se inventa una confirmación.
- `telegram_message_id`, cuando existe, es la prueba de envío: si
  un intento posterior encuentra ese id para el mismo recordatorio,
  no vuelve a enviar.

### 3.11. telegram_link_attempts (intentos de vinculación, antifraude)

| Columna | Tipo | Restricción |
|---|---|---|
| id | BIGINT | PK |
| chat_id | BIGINT | NOT NULL (quien intentó, aunque no esté vinculado) |
| telegram_user_id | BIGINT | NULL (si Telegram lo proporciona) |
| attempted_code_hash | VARCHAR(64) | NULL (hash del código intentado, para auditar sin guardar códigos) |
| success | BOOLEAN | NOT NULL |
| attempted_at | TIMESTAMPTZ | NOT NULL |
| reason | VARCHAR(50) | NULL (ej. 'INVALIDO', 'VENCIDO', 'LIMITADO'; nunca distingue más de lo necesario en el mensaje al usuario) |

Se usa solo para el límite de intentos (§7.3): 5 fallos desde el
mismo `chat_id` en 15 minutos bloquean nuevos intentos desde ese
chat durante 15 minutos. Los intentos de más de 24 horas se ignoran
para el límite y pueden purgarse en una tarea de limpieza (Fase 6);
no son historial clínico y no necesitan conservarse indefinidamente.

## 4. Entidades adicionales evaluadas (y por qué estas sí, y otras no)

- **refresh_tokens: sí.** Sin ella, un refresh robado no se puede
  revocar y el cierre de sesión sería mentira.
- **notification_logs: sí.** Es la prueba de que un aviso se envió
  (o falló, o quedó ambiguo) y el freno contra reenvíos: si ya hay
  `telegram_message_id`, no se vuelve a enviar ese recordatorio.
- **telegram_link_attempts: sí.** Sin una tabla, el límite de
  intentos por `chat_id` dependería de memoria que se pierde al
  reiniciar el bot, y un atacante podría probar códigos sin dejar
  rastro. Es una tabla de seguridad, no de negocio.
- **No se añade** una tabla de "pacientes": el usuario gestiona sus
  propios tratamientos (ver límite en el README).
- **No se añade** una tabla de "farmacias" ni de "médicos": no hay
  requisito que la pida y sería relleno.
- **No se añade** una tabla de auditoría genérica: `notification_logs`
  e `intakes` ya cubren lo que hay que demostrar; una auditoría total
  se puede añadir en una versión futura sin cambiar este modelo.

## 5. Índices recomendados

```sql
-- Búsquedas por usuario (todas las consultas de negocio filtran por user_id)
CREATE INDEX idx_medications_user ON medications(user_id, is_active);
CREATE INDEX idx_treatments_user ON treatments(user_id, status);
CREATE INDEX idx_treatment_meds_treatment ON treatment_medications(treatment_id);

-- El motor y las vistas de "próximos": la consulta más caliente del sistema
CREATE INDEX idx_reminders_user_scheduled ON medication_reminders(user_id, scheduled_at);
CREATE INDEX idx_reminders_status_scheduled ON medication_reminders(status, scheduled_at)
  WHERE status IN ('PENDIENTE', 'ENVIANDO');
CREATE UNIQUE INDEX uq_reminders_schedule_time
  ON medication_reminders(schedule_id, scheduled_at);

-- Historial y estadísticas
CREATE INDEX idx_intakes_user_taken ON medication_intakes(user_id, taken_at DESC);
CREATE INDEX idx_logs_reminder ON notification_logs(reminder_id, attempted_at DESC);
CREATE INDEX idx_logs_reconciliation ON notification_logs(status, attempted_at)
  WHERE status = 'AMBIGUA';

-- Vinculación y sesiones
CREATE UNIQUE INDEX uq_telegram_user ON telegram_accounts(telegram_user_id)
  WHERE telegram_user_id IS NOT NULL;
CREATE INDEX idx_refresh_user ON refresh_tokens(user_id, expires_at);
CREATE INDEX idx_link_attempts_chat ON telegram_link_attempts(chat_id, attempted_at DESC);

-- Claves compuestas (id, user_id) para las FK de §7
CREATE UNIQUE INDEX uq_medications_id_user ON medications(id, user_id);
CREATE UNIQUE INDEX uq_treatments_id_user ON treatments(id, user_id);
CREATE UNIQUE INDEX uq_treatment_meds_id_user ON treatment_medications(id, user_id);
CREATE UNIQUE INDEX uq_schedules_id_user ON medication_schedules(id, user_id);
CREATE UNIQUE INDEX uq_reminders_id_user ON medication_reminders(id, user_id);
```

## 6. Reglas de conservación del historial

1. Nunca `DELETE` en `treatments`, `treatment_medications`,
   `medication_schedules`, `medication_reminders` ni `medication_intakes`
   desde la aplicación. Cancelar = cambiar `status`; desactivar =
   `is_active = FALSE`.
2. Cambiar un horario futuro no reescribe recordatorios ya tomados ni
   perdidos: solo afecta a los `PENDIENTE` futuros (que se regeneran)
   y deja intacto el pasado.
3. Un usuario que desactiva su cuenta (`is_active = FALSE`) conserva
   sus datos; el borrado físico, si algún día se exige por normativa,
   sería un proceso aparte, documentado y fuera de esta versión.

## 7. Integridad entre cuentas (que un usuario no pueda tocar datos de otro)

### 7.1. El problema que una FK simple no resuelve

Una FK simple (`treatment_id → treatments.id`) solo comprueba que
el tratamiento existe. Nada impide, con FK simples, crear un vínculo
entre el tratamiento del usuario A y el medicamento del usuario B, o
una toma del usuario A sobre un recordatorio del usuario B, si el
servicio tiene un error. La base de datos lo aceptaría en silencio.

### 7.2. Defensa en dos capas (las dos son obligatorias, ninguna basta sola)

**Capa 1 — Servicio (siempre):** antes de crear o modificar cualquier
hijo, el servicio carga el padre y comprueba `padre.user_id ==
usuario_actual`. Además, toda consulta de lectura filtra por
`user_id`. Un ID adivinado de otro usuario debe devolver 403 (o 404
genérico, según se decida en la Fase 3, pero nunca datos). Checklist
por operación:

| Operación | Validación obligatoria en el servicio |
|---|---|
| Crear medicamento | El medicamento nuevo lleva el `user_id` del token, nunca el del cuerpo |
| Crear tratamiento | Igual; el `user_id` nunca viene del cliente |
| Añadir medicamento a un tratamiento | Tratamiento y medicamento existen **y** ambos son del usuario actual |
| Crear/editar horario | El `treatment_medication` padre es del usuario actual |
| Generar recordatorios | Solo desde horarios de tratamientos del usuario; el generador nunca mezcla usuarios en una tanda |
| Confirmar/posponer toma | El recordatorio es del usuario (web: token; bot: `chat_id` vinculado) y sigue en estado válido |
| Cancelar tratamiento | El tratamiento es del usuario; se cancelan solo sus recordatorios pendientes |
| Vincular Telegram | El código pertenece a la cuenta que lo generó en la web |
| Consultar historial/estadísticas | Todas las consultas llevan `user_id` en el WHERE |

**Capa 2 — Base de datos (red de seguridad):** `user_id`
desnormalizado en `treatment_medications`, `medication_schedules`,
`medication_reminders`, `medication_intakes` y `notification_logs`,
más FK compuestas `(padre_id, user_id) → padre(id, user_id)` y
UNIQUE `(id, user_id)` en cada padre (ver §3 y §5). Con esto, un
error del servicio que intentara cruzar cuentas fallaría en la
transacción con error de FK, en lugar de corromper datos.

**No se usa Row Level Security (RLS) en v1.** RLS con conexiones
agrupadas y sesiones async exigiría fijar el rol por petición y
añadiría una capa de fallo difícil de depurar para el equipo. Queda
como mejora futura documentada, no como promesa. La combinación
servicio + FK compuesta es suficiente y demostrable en la Fase 2
con una prueba que intenta el cruce y espera el fallo.

### 7.3. Códigos de vinculación de Telegram (seguridad completa)

- **Generación:** `secrets.choice` (módulo `secrets` de Python, no
  `random`) sobre un alfabeto de 32 caracteres sin confusiones
  (`ABCDEFGHJKLMNPQRSTUVWXYZ23456789`, sin O, I, 0 ni 1), longitud
  **10 caracteres** (50 bits de entropía). El código se muestra una
  sola vez en la web; después solo existe su hash.
- **Almacenamiento:** HMAC-SHA256 del código con el secreto dedicado
  `TELEGRAM_LINK_SECRET` (en `.env`, distinto del secreto JWT y del
  token del bot). Comparación con `hmac.compare_digest` (tiempo
  constante). Nunca se guarda el código en texto plano, nunca se
  registra en logs y nunca se devuelve por la API.
- **Expiración y un solo uso:** 15 minutos desde su creación. Al
  vincular con éxito, al expirar o al revocarse, `link_code_hash` y
  `link_expires_at` pasan a NULL en la misma transacción que cambia
  el estado. Un código expirado no se puede "reactivar".
- **Límite de intentos y fuerza bruta:** cada intento (éxito o fallo)
  se registra en `telegram_link_attempts`. Si un mismo `chat_id`
  acumula **5 fallos en 15 minutos**, se bloquean nuevos intentos
  desde ese chat durante 15 minutos. Además, un código concreto que
  acumule 5 fallos se invalida (su fila pasa a REVOCADA y hay que
  generar otro en la web). El espacio de códigos (50 bits) más la
  expiración de 15 minutos hace inviable adivinar un código válido
  dentro de su vida útil con ese límite.
- **Sin oráculo:** el bot responde lo mismo ante código inexistente,
  vencido, ya usado o bloqueado por intentos: "Código inválido o
  vencido. Genera uno nuevo en la web." No se distingue el motivo en
  el mensaje, para no confirmar al atacante qué códigos existen.
- **Canal:** el código solo debe escribirse en el chat privado con
  el bot, nunca en un grupo. Tras procesar `/vincular`, el bot
  intenta borrar el mensaje del usuario (best effort: la API puede
  no permitirlo en todos los casos); como el código es de un solo
  uso, un código ya usado que quedara visible no sirve para vincular.
- **Revocación:** desvincular desde la web marca la cuenta REVOCADA,
  borra el código pendiente y hace que el scheduler deje de enviar
  a ese `chat_id` y el bot deje de obedecerlo.

## 8. Zonas horarias (UTC dentro, hora local fuera)

### 8.1. Reglas

- **Dentro:** todo instante (`scheduled_at`, `taken_at`,
  `attempted_at`, `sent_at`, `created_at`, `updated_at`) es
  `TIMESTAMPTZ` en UTC. La base de datos nunca guarda una hora
  local sin zona.
- **Horarios:** `medication_schedules.times` es `TIME` sin zona:
  es una hora de pared ("a las 08:00"), no un instante. El instante
  concreto se calcula al generar el recordatorio.
- **Fechas:** `start_date` y `end_date` son `DATE` de calendario en
  la zona del usuario, no fechas UTC. Un tratamiento que empieza
  "el 10 de noviembre" empieza ese día donde vive el usuario.
- **Nunca datetimes ingenuos:** en los servicios, toda fecha-hora
  es aware (con zona). Un datetime sin zona es un error de
  programación y debe fallar en revisión, no llegar a la BD.
- **Zona del usuario:** `users.timezone` es un nombre IANA
  (`America/Bogota`, `America/Mexico_City`…), validado contra
  `zoneinfo.available_timezones()` en la Fase 3. No se aceptan
  desplazamientos fijos tipo "-05:00" como zona, porque no saben
  de horario de verano.
- **Dependencia en Windows:** `zoneinfo` en Windows necesita el
  paquete `tzdata` (en Linux/macOS suele venir del sistema). Se
  añade como dependencia justificada en la Fase 1; sin ella, la
  generación de recordatorios en el PC de desarrollo fallaría.

### 8.2. Generación de un recordatorio

Para cada fecha del calendario del usuario y cada hora del horario:

1. Se toma la fecha local + la hora local + `ZoneInfo(usuario.timezone)`.
2. Se convierte a UTC y ese es `scheduled_at`.
3. Se inserta con la restricción única `(schedule_id, scheduled_at)`,
   así que regenerar no duplica.

### 8.3. Horario de verano (DST): los dos casos difíciles

- **Hora inexistente (adelanto, ej. 02:30 que no existe ese día):**
  no se omite la toma en silencio. Se desplaza hacia adelante hasta
  la primera hora local válida de ese día y se deja constancia en
  la generación (el recordatorio queda a esa hora desplazada, no a
  una hora imposible).
- **Hora ambigua (retraso, ej. 01:30 que ocurre dos veces):** se usa
  la primera ocurrencia (`fold=0`). No se generan dos recordatorios
  para la misma hora local.
- Colombia (`America/Bogota`) no observa DST hoy, pero el sistema
  no puede asumirlo: un usuario puede cambiar de zona o vivir
  donde sí hay DST, y la sustentación debe poder explicar estos
  casos aunque no ocurran en la demo.

### 8.4. Cambio de zona horaria del usuario

- Los recordatorios **ya enviados, tomados o perdidos no cambian**:
  son historia con instantes UTC fijos.
- Los recordatorios `PENDIENTE` futuros se recalculan: al cambiar
  `users.timezone`, el servicio cancela los `PENDIENTE` con
  `scheduled_at` futuro y regenera los próximos 7 días con la nueva
  zona, manteniendo la misma hora de pared (08:00 sigue siendo
  08:00 en el nuevo lugar). Esta operación se confirma en la web
  ("los avisos futuros se recalcularán") y queda registrada como
  una regeneración, no como un borrado silencioso.
- Las fechas de inicio/fin de tratamientos y horarios no se
  reescriben: son fechas de calendario y se reinterpretan con la
  nueva zona solo para la generación futura.

### 8.5. Qué ve el frontend

La API devuelve instantes ISO 8601 en UTC. El frontend los muestra
con la zona del usuario (API `Intl` del navegador), nunca
reinterpretando la hora UTC como si fuera local. Un error típico
que se debe evitar en la Fase 8: mostrar `scheduled_at` sin convertir
desplazaría todas las horas en la diferencia con UTC.

## 9. Idempotencia y reconciliación (corrección de la promesa anterior)

### 9.1. Lo que Telegram Bot API sí permite y lo que no

La API de Telegram **no ofrece claves de idempotencia** en
`sendMessage` ni una forma de consultar "¿ya enviaste este mensaje?".
La única confirmación de envío es la respuesta de la llamada, que
incluye `telegram_message_id`. Por tanto:

- **No se puede prometer "exactamente una vez" en la entrega del
  mensaje.** Si la red falla entre el envío y la respuesta, el
  mensaje puede haber llegado sin que el sistema lo sepa, y un
  reintento podría duplicarlo. Cualquier documento anterior que
  prometiera envío exactamente una vez queda corregido por esta
  sección.
- **Sí se puede prometer "exactamente una vez" en el efecto:**
  una toma solo se crea una vez por recordatorio
  (`medication_intakes.reminder_id` UNIQUE + transición de estado),
  y confirmar dos veces (por ejemplo, desde dos mensajes duplicados)
  es una operación idempotente: la segunda confirmación no crea
  otra toma.
- **Garantía realista del sistema: entrega al menos una vez,
  efecto exactamente una vez, y ningún fallo silencioso.** Un
  aviso puede, en el peor caso (respuesta perdida), llegar
  duplicado; nunca debe perderse sin quedar registrado como
  FALLIDA o AMBIGUA, ni crear dos tomas.

### 9.2. El mecanismo, paso a paso

1. **Reclamación:** en una transacción, el scheduler pasa el
   recordatorio de `PENDIENTE` a `ENVIANDO`, genera un
   `current_attempt_id` (UUID nuevo por intento), guarda
   `claimed_at = now()` e incrementa `attempt_count`.
2. **Intento registrado:** se crea una fila en
   `notification_logs` con `attempt_id`, `attempted_at = now()`
   y estado provisional. Si la llamada falla de forma clara
   (error de la API: chat no encontrado, bot bloqueado), la fila
   queda `FALLIDA`, `sent_at` NULL, y el recordatorio vuelve a
   `PENDIENTE` con `next_attempt_at` y backoff, hasta 3 intentos.
   Tras el tercer fallo claro, el recordatorio pasa a `FALLIDA`
   y queda visible en la web como aviso no entregado.
3. **Éxito:** si la API responde, se guarda `telegram_message_id`
   y `sent_at`, la fila queda `ENVIADA` y el recordatorio pasa a
   `ENVIADA`. A partir de aquí, ningún reintento vuelve a enviar
   ese recordatorio.
4. **Caso ambiguo (respuesta perdida):** si la llamada no devuelve
   respuesta ni error claro (timeout, caída de red tras enviar),
   la fila queda `AMBIGUA` (`sent_at` NULL, `telegram_message_id`
   NULL) y el recordatorio queda en `ENVIANDO` con su
   `current_attempt_id`. **No se reenvía de inmediato**: un reenvío
   inmediato es justo lo que duplicaría el mensaje si el primero
   sí llegó.
5. **Reconciliación (tarea del scheduler, no una consulta a
   Telegram, porque la API no permite verificar envíos):** cada
   ciclo, el scheduler busca `ENVIANDO` con `claimed_at` de más
   de 5 minutos y `AMBIGUA` sin `telegram_message_id`:
   - Si ya existe una fila `ENVIADA` con `telegram_message_id`
     para ese recordatorio (el éxito llegó por otro camino), se
     marca `ENVIADA` y no se reenvía.
   - Si no existe, se hace **un único reintento** tras 10 minutos
     desde el intento ambiguo, con un nuevo `attempt_id`. Si este
     reintento tiene éxito, queda `ENVIADA`; si falla de forma
     clara, se aplica el backoff de §9.2.2; si vuelve a ser
     ambiguo, tras 3 intentos ambiguos el recordatorio pasa a
     `FALLIDA` con error "entrega ambigua, reintentos agotados".
   - Un recordatorio `FALLIDA` no se reenvía automáticamente días
     después: el usuario lo ve en la web y puede actuar (por
     ejemplo, confirmar manualmente la toma).
6. **Reinicio:** al arrancar, el scheduler recarga los `PENDIENTE`
   en la cola y trata los `ENVIANDO` antiguos exactamente como en
   el punto 5 (reconciliación, no reenvío ciego). Los `ENVIADA`
   con `telegram_message_id` nunca se reenvían.
7. **Botones idempotentes:** el `callback_data` de Tomada/Posponer
   lleva solo el `reminder_id`. Confirmar un recordatorio ya en
   `TOMADA` devuelve "ya registrada" sin crear otra toma; posponer
   un recordatorio ya pospuesto no crea un segundo hijo. Así, un
   mensaje duplicado por el caso ambiguo no duplica el efecto.

### 9.3. Qué se prueba en la Fase 5 (criterio corregido)

El criterio duro anterior ("envío exactamente una vez en tres
escenarios") se sustituye por este, que sí es verificable:

- En escenario normal, el aviso se envía una vez y queda `ENVIADA`
  con `telegram_message_id`.
- Tras doble reclamación en paralelo, solo un intento envía.
- Tras reinicio, los `PENDIENTE` se recargan y los `ENVIADA` no se
  reenvían.
- En fallo claro simulado, el recordatorio termina `FALLIDA` tras
  3 intentos y queda registrado, no perdido en silencio.
- En respuesta perdida simulada, el sistema registra `AMBIGUA`,
  no inventa una confirmación, y la reconciliación decide con un
  único reintento; la toma, si se confirma desde cualquiera de los
  mensajes, se crea una sola vez.
