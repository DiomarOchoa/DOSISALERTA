# DECISIONES TÉCNICAS — DosisAlerta

Fase 0. Cada decisión tiene: qué se decidió, por qué, qué se rechazó
y cómo se verificará. Si una decisión cambia en una fase posterior,
se añade una entrada nueva con fecha; no se borra la anterior sin
dejar rastro.

## 1. Stack y arquitectura

### D01. Python 3.12+ con FastAPI como único backend

- **Decisión:** toda la lógica de negocio vive en Python con FastAPI.
- **Por qué:** es el requisito oficial de la asignatura (aplicación
  real en Python). Además, FastAPI genera la documentación OpenAPI/
  Swagger sola, valida con Pydantic y su modelo async encaja con el
  bot de Telegram, que también es async.
- **Rechazado:** cualquier backend en otro lenguaje distinto de
  Python, y cualquier reparto de la lógica entre dos backends. Un
  segundo backend duplicaría reglas, rompería la sincronización
  web ↔ Telegram y pondría en riesgo el requisito 1 de la asignatura.
- **Verificación:** Fase 1 — el repositorio no contiene ningún otro
  backend y `pyproject.toml` es la única fuente de dependencias.

### D02. Monolito modular, no microservicios

- **Decisión:** un solo código, organizado por capas y por dominio,
  con dos procesos (API y bot) que comparten servicios.
- **Por qué:** el equipo es universitario, el plazo es de 21 días y
  el problema no exige escalar servicios por separado. Partirlo
  añadiría red, despliegue y fallos distribuidos sin ningún beneficio
  demostrable.
- **Rechazado:** microservicios, y también un monolito sin capas
  (todo en los routers), que haría imposible reutilizar la lógica
  entre web y bot.
- **Verificación:** Fase 4 — un cambio de regla en un servicio se
  refleja en web y bot sin tocar dos sitios.

### D03. Dos procesos (API + bot), un código, una base de datos

- **Decisión:** ver `ARQUITECTURA.md` §3.
- **Por qué:** el bot atiende mensajes entrantes y el scheduler envía
  avisos; son ritmos distintos y conviene poder reiniciar uno sin
  tumbar el otro, sin convertirlos en proyectos separados.
- **Rechazado:** meter el bot dentro de las rutas HTTP de FastAPI
  (mezclaría dos protocolos en un mismo proceso y complicaría el
  polling) y, en el otro extremo, un repositorio aparte para el bot
  (duplicaría modelos y servicios).
- **Verificación:** Fase 6 — bot y API corren a la vez contra la
  misma BD y una toma confirmada en Telegram aparece en la API.

### D04. SQLAlchemy 2.0 async + Alembic (nunca create_all como evolución)

- **Decisión:** ORM async con `asyncpg`; migraciones Alembic desde
  la primera tabla.
- **Por qué:** async en todo el backend (una sola forma de trabajar
  con la BD, coherente con FastAPI y con el bot async) y migraciones
  versionadas: el esquema tiene historia y se puede revertir.
- **Rechazado:** `create_all` en cada arranque (destruye la historia
  del esquema y no sirve cuando los datos ya existen) y SQL escrito a
  mano en cada consulta (pierde el tipado y la reutilización).
- **Verificación:** Fase 2 — `alembic upgrade head` desde cero crea
  las 11 tablas (incluida `telegram_link_attempts`, añadida en la
  revisión técnica por seguridad de vinculación).

### D05. PostgreSQL 17, no SQLite para el proyecto

- **Decisión:** PostgreSQL 17-alpine en Docker para desarrollo; la
  misma familia en cualquier despliegue posterior.
- **Por qué:** es la base de datos exigida en el diseño, soporta
  tipos, índices parciales y restricciones que el modelo usa, y evita
  sorpresas de cambiar de motor al final (fechas, zonas horarias y
  concurrencia se comportan distinto en SQLite).
- **Rechazado:** SQLite como BD del proyecto (válida solo, si acaso,
  para una prueba unitaria aislada sin BD, nunca como fuente de verdad).
- **Verificación:** Fase 1 — `docker compose up -d postgres` y
  `pg_isready` en verde.

### D06. Pydantic v2 en la frontera

- **Decisión:** todo lo que entra y sale de la API pasa por esquemas
  Pydantic; los modelos SQLAlchemy nunca se devuelven tal cual.
- **Por qué:** separa el contrato público del esquema interno (se
  puede cambiar una columna sin romper la web) y valida tipos,
  rangos y formatos antes de tocar la lógica.
- **Verificación:** Fase 3 — un cuerpo inválido devuelve 400 con un
  mensaje claro, no un error 500.

### D07. pyproject.toml, no requirements.txt duplicado

- **Decisión:** `pyproject.toml` como única fuente de dependencias
  Python. El requisito oficial pide `requirements.txt` **o**
  `pyproject.toml`: se cumple con uno, no con dos que puedan divergir.
- **Por qué:** es el formato moderno, permite instalación editable
  (`pip install -e .`) y metadatos del proyecto en un solo sitio.
- **Nota:** si el docente pide explícitamente un `requirements.txt`,
  se genera con `pip freeze` a partir del entorno instalado, sin
  mantener dos listas a mano.
- **Verificación:** Fase 1 — instalación limpia desde `pyproject.toml`.

## 2. Telegram

### D08. Polling, no webhook, en desarrollo

- **Decisión:** python-telegram-bot con polling (`Application` en
  `python -m app.bot.main`).
- **Por qué:** el polling no necesita dominio público, certificado
  TLS ni exponer un puerto a Internet. Funciona en local, detrás de
  NAT, que es exactamente el entorno de desarrollo y de demo del equipo.
- **Rechazado (por ahora):** webhook. Es la opción correcta en
  producción con dominio y HTTPS, pero exigirla en desarrollo
  añadiría infraestructura antes de tener bot que probar. Queda como
  opción documentada para la Fase 9 si hay despliegue público.
- **Verificación:** Fase 6 — el bot responde sin ningún servidor
  público levantado.

### D09. El bot solo llama a servicios, nunca a la BD

- **Decisión:** los handlers traducen mensajes/botones a llamadas a
  servicios; no importan repositorios para escribir ni hacen SQL.
- **Por qué:** es la única forma de garantizar que web y Telegram
  apliquen las mismas reglas y los mismos controles de propiedad.
- **Verificación:** Fase 6 — revisión de imports del paquete `bot/`
  (servicios y esquemas, no repositorios).

### D10. Vinculación por código de un solo uso (revisada)

- **Decisión:** código de 10 caracteres, alfabeto de 32 sin
  confusiones, generado con `secrets` (no `random`), 15 minutos de
  vida, guardado solo como HMAC-SHA256 con el secreto dedicado
  `TELEGRAM_LINK_SECRET` y comparado con `hmac.compare_digest`,
  un solo uso, fila en `telegram_accounts` en estado `PENDIENTE`
  hasta confirmar, y borrado del hash al vincular, expirar o revocar.
  Intentos registrados en `telegram_link_attempts`: 5 fallos por
  `chat_id` en 15 minutos bloquean ese chat 15 minutos, y 5 fallos
  sobre un código lo invalidan. Mensaje genérico ante cualquier
  fallo (inexistente, vencido, usado o bloqueado), para no dar un
  oráculo al atacante.
- **Por qué:** no exige que el usuario escriba su contraseña en
  Telegram (nunca debe hacerlo) y no depende de compartir el
  `chat_id` a mano, que el usuario no conoce. El HMAC con secreto
  dedicado protege el hash aunque se filtre la BD (un SHA simple de
  un código corto sería atacable por diccionario); el límite por
  `chat_id` en BD (no en memoria) sobrevive a reinicios del bot.
- **Rechazado:** vincular por correo/contraseña dentro del bot;
  vincular por enlace con el `user_id` en la URL (filtrable y
  reutilizable); guardar el código en texto plano o con hash sin
  secreto; y limitar solo por código (un atacante que prueba
  códigos al azar no incrementaría ningún contador concreto).
- **Verificación:** Fase 6 — código reutilizado, vencido o con 5
  fallos es rechazado con el mismo mensaje genérico; el sexto intento
  desde el mismo `chat_id` en 15 minutos queda bloqueado.

## 3. Frontend

### D11. React + Vite + TypeScript (no JavaScript plano)

- **Decisión:** TypeScript en todo el frontend.
- **Por qué:** los tipos de la API (DTOs) se comparten como tipos
  TypeScript; un cambio de campo en el backend que no se refleja en
  la web se detecta al compilar, no al pulsar el botón en la demo.
  Vite lo soporta sin configuración extra y el coste de aprendizaje
  es bajo: es JavaScript con tipos.
- **Rechazado:** JavaScript plano (más rápido de escribir el primer
  día, más frágil el día de la demo) y un framework CSS pesado
  (innecesario para este alcance; CSS moderno con variables basta y
  se explica en un minuto).
- **Verificación:** Fase 8 — `npm run build` en verde, sin errores
  de tipo, y ninguna vista con datos hardcodeados.

### D12. Sin WebSocket ni tiempo real en esta versión

- **Decisión:** la web recarga datos al entrar a cada vista y después
  de cada acción.
- **Por qué:** ningún requisito exige tiempo real; el aviso en vivo
  lo da Telegram, que es el canal de notificación. Añadir WebSocket
  sumaría un protocolo, autenticación de socket y estados, sin
  cambiar ninguna funcionalidad exigida.
- **Verificación:** Fase 8 — checklist de flujos sin conexión
  persistente.

## 4. Seguridad

### D13. JWT access + refresh (con refresh guardado y revocable)

- **Decisión:** access de 60 minutos, refresh de 7 días guardado con
  hash en `refresh_tokens`; cerrar sesión lo revoca.
- **Por qué:** un access corto limita el daño si se filtra; el
  refresh permite no pedir la contraseña cada hora sin renunciar a
  poder revocarlo. Guardar solo el hash hace que una filtración de
  la BD no entregue sesiones válidas directamente.
- **Rechazado:** solo access sin refresh (mala experiencia), sesiones
  en memoria del servidor (se pierden al reiniciar y no escalan) y
  contraseñas en texto plano (nunca, bajo ningún pretexto).
- **Verificación:** Fase 3 — pruebas de expiración y revocación.

### D14. bcrypt para contraseñas

- **Decisión:** bcrypt con salt por contraseña, a través de la
  librería `bcrypt`.
- **Por qué:** es el estándar explicado en cualquier curso de
  seguridad, lento a propósito contra fuerza bruta y sin secretos
  adicionales que gestionar.
- **Verificación:** Fase 3 — la columna `password_hash` nunca
  contiene la contraseña original ni en datos de prueba.

## 5. Motor de recordatorios

### D15. Cola de prioridad propia detrás de una interfaz, con heapq de respaldo

- **Decisión:** `app/algorithms/ReminderHeap`: heap binario propio
  (subir/bajar, inserción y extracción), usado por el scheduler a
  través de una interfaz de cola de prioridad. La misma interfaz
  tiene una implementación con `heapq` de la biblioteca estándar.
- **Por qué:** la asignatura exige demostrar estructuras de datos
  reales. La cola de prioridad es el corazón del motor (siempre el
  próximo aviso primero), así que implementarla tiene utilidad
  técnica demostrable, no es adorno. El respaldo con `heapq` existe
  para que, si la implementación propia falla sus pruebas en la
  Fase 5, el envío no se quede sin cola: se cambia la implementación,
  no el scheduler.
- **Rechazado:** usar solo `heapq` sin implementación propia (no
  demostraría la estructura) y, en el otro extremo, usar la
  implementación propia sin pruebas ni respaldo (pondría el envío
  real en manos de código sin red).
- **Verificación:** Fase 5 — pruebas de propiedades del heap contra
  `heapq` (mismo orden de extracción con las mismas inserciones) y
  el criterio duro corregido: entrega al menos una vez, efecto
  exactamente una vez, ningún fallo silencioso (ver D18 revisada).

### D16. Diccionarios (hash map) como índice, no como fuente de verdad

- **Decisión:** `jobs_by_id: dict[int, Job]` y
  `jobs_by_user: dict[int, set[int]]` en el scheduler, para cancelar
  o reprogramar en O(1).
- **Por qué:** recorrer la cola para buscar un recordatorio sería
  O(n) en cada cancelación; el dict da acceso directo y es la
  estructura natural de Python para este índice.
- **Límite:** el dict es una caché. Si se pierde (reinicio), se
  reconstruye desde BD. Nunca se decide un envío solo por el dict.
- **Verificación:** Fase 5 — cancelar un tratamiento invalida sus
  entradas sin recorrer toda la cola (prueba de comportamiento, no
  de microbenchmark).

### D17. Ordenamiento con la ordenación incorporada, no con un algoritmo propio

- **Decisión:** listas (próximos, historial) ordenadas con `sorted`
  (Timsort, O(n log n)) y con `ORDER BY` en BD cuando el orden viene
  de la consulta.
- **Por qué:** reescribir un algoritmo de ordenación para producción
  sería artificial: no aporta nada frente a una implementación
  probada durante décadas, y la asignatura pide estructuras con
  utilidad, no estructuras por rellenar. En la sustentación se
  explica Timsort y por qué no se reinventó.
- **Verificación:** Fase 7 — el historial sale ordenado y el conteo
  de cumplimiento coincide con el conteo manual.

### D18. Persistencia primero, memoria después; reclamación y reconciliación (revisada)

- **Decisión:** la BD es la verdad; la cola es una vista ordenada de
  los `PENDIENTE`. Enviar exige reclamar: una transacción que pasa
  el recordatorio de `PENDIENTE` a `ENVIANDO` con un
  `current_attempt_id` nuevo, `claimed_at` y `attempt_count`
  incrementado; solo quien reclama envía. Cada intento queda en
  `notification_logs` (`attempted_at` siempre; `sent_at` y
  `telegram_message_id` solo si Telegram confirma). Un intento sin
  respuesta clara queda `AMBIGUA` y se decide en reconciliación
  (único reintento tras 10 minutos; tras 3 ambiguos, `FALLIDA`),
  nunca con reenvío inmediato ni con una confirmación inventada.
  La API de Telegram no ofrece idempotencia ni verificación de
  envíos, así que la promesa es entrega al menos una vez y efecto
  exactamente una vez, no envío exactamente una vez.
- **Por qué:** sin reclamación, dos tareas o dos reinicios podrían
  enviar el mismo aviso. Sin borrado perezoso, cancelar obligaría a
  reconstruir la cola entera. Sin el estado `AMBIGUA`, un fallo de
  red tras el envío se registraría como éxito o como fallo, y ambas
  mentiras son peores que reconocer la ambigüedad.
- **Verificación:** Fase 5 — doble reclamación en paralelo: solo una
  envía; respuesta perdida simulada queda `AMBIGUA` y se reconcilia;
  confirmar dos veces crea una sola toma.

### D19. Una sola instancia API en esta versión

- **Decisión:** el diseño asume una instancia del proceso API. No se
  promete multi-instancia.
- **Por qué:** con dos schedulers, la reclamación en BD seguiría
  evitando duplicados en la mayoría de casos, pero el diseño no se
  ha probado para ese escenario y prometerlo sería vender humo.
  Escalar exigiría un bloqueo distribuido y queda fuera de alcance,
  documentado en `ARQUITECTURA.md` §9.
- **Verificación:** Fase 9 — la documentación de despliegue dice
  explícitamente "una instancia API".

### D20. Integridad entre cuentas: servicio + FK compuestas (revisión técnica)

- **Decisión:** `user_id` desnormalizado en las tablas hijas y FK
  compuestas `(padre_id, user_id) → padre(id, user_id)`, con UNIQUE
  `(id, user_id)` en cada padre, además de la validación en el
  servicio (padre del mismo usuario + filtro `user_id` en toda
  consulta). Detalle y checklist en `MODELO_DATOS.md` §7.
- **Por qué:** una FK simple no impide cruzar cuentas; solo el par
  lo impide en la transacción, incluso si el servicio tiene un error.
- **Rechazado (en v1):** Row Level Security de PostgreSQL (exigiría
  fijar rol por petición con conexiones agrupadas async, difícil de
  depurar para el equipo). Queda como mejora futura, no como promesa.
- **Verificación:** Fase 2 — intento de cruce de cuentas falla por FK.

### D21. Zonas horarias: UTC dentro, hora local fuera (revisión técnica)

- **Decisión:** instantes UTC en BD; horas de horario como horas de
  pared; fechas como fechas de calendario en la zona IANA del
  usuario; generación con `ZoneInfo`; hora inexistente en DST:
  desplazar a la primera válida; hora ambigua: primera ocurrencia;
  cambio de zona: recalcular solo los `PENDIENTE` futuros.
  Dependencia `tzdata` justificada para Windows en la Fase 1.
- **Por qué:** mezclar horas locales sin zona es la causa clásica
  de avisos a la hora equivocada tras un cambio de horario o de
  zona, y Colombia no tener DST hoy no exime al sistema de
  resolverlo para cualquier zona.
- **Verificación:** Fase 4 — generación con una zona con DST en
  pruebas (ej. hora inexistente y ambigua) produce lo documentado,
  no una omisión silenciosa ni un duplicado.

## 6. Cuidadores e IA (decisiones del 2026-11-11)

### D22. Familiares y cuidadores incluidos en la versión 1

Un paciente puede vincular uno o varios cuidadores autorizados
y un cuidador puede estar vinculado a uno o varios pacientes,
siempre mediante autorización explícita. Relación muchos a
muchos mediante `caregiver_links` + `caregiver_audit_log`
(13 tablas en total, 2 nuevas en la migración inicial de la
Fase 2). Diseño en `docs/database/RELACIONES_CUIDADORES.md`;
requisitos RF20–RF22.

### D23. Permisos del cuidador: independientes, explícitos y con límites duros

8 permisos independientes (consultar medicamentos, tratamientos,
horarios, próximas tomas e historial; recibir notificaciones
autorizadas; gestionar medicamentos; gestionar horarios), todos
en NO por defecto y concedidos explícitamente por el paciente.
La gestión nunca permite modificar dosis prescritas, cambiar
indicaciones médicas ni suspender tratamientos. No existe permiso
para confirmar tomas en nombre del paciente. El botón
«NO LO HE TOMADO» está eliminado definitivamente: los botones
aprobados son YA LO TOMÉ y RECORDARME DESPUÉS.

### D24. Módulo de IA híbrido como Fase 10 propuesta, post-entrega

Arquitectura híbrida Gemini API + Ollama local aprobada; su
implementación se propone para una Fase 10 posterior a la
entrega académica del 25 de noviembre y no forma parte de los
compromisos de la entrega ni de la sustentación. F1–F9
permanecen intactas. Diseño en `docs/architecture/MODULO_IA.md`.
El consentimiento para usar IA y su almacenamiento se diseñan
en la fase de implementación de IA, no en la Fase 2.

### D25. Tabla 14 `caregiver_link_attempts` (aprobada 2026-11-11)

Espejo de `telegram_link_attempts` para la protección contra
fuerza bruta de los códigos de invitación de cuidador. Cada
intento se registra con `chat_id`, hash del código intentado y
motivo, antes de saber si el código es correcto: el límite de
5 fallos por `chat_id` en 15 minutos se cuenta por identidad
del chat y ventana temporal, sin necesidad de conocer el código
correcto. Su estructura queda documentada desde ahora
(`MODELO_DATOS.md` §3.14, `RELACIONES_CUIDADORES.md` §13); su
migración física es de la Fase 6, porque es el bot quien recibe
los códigos y escribe los intentos. La Fase 2 no se bloquea.

### D26. Columna `details JSONB` en `caregiver_audit_log` con minimización de datos (aprobada 2026-11-11)

La auditoría registra el detalle mínimo necesario de cada
acción (nombre del permiso o del campo que cambió y sus valores
anterior y nuevo cuando el cambio es ese campo). **Nunca** se
guardan tokens, secretos, códigos de invitación (ni su hash),
contraseñas, dosis, concentraciones, nombres de medicamentos ni
indicaciones médicas innecesarias. Si un dato no está en la
lista de permitidos, no se guarda.

### D27. Interpretación estrecha de "gestionar horarios" (aprobada 2026-11-11)

Con `perm_manage_schedules` el cuidador únicamente puede
modificar las horas (`times`) de horarios existentes, con
autorización explícita. No puede crear horarios ni cambiar
frecuencia, días de la semana o intervalos: esas operaciones
las hace solo el paciente. Cierra la tensión entre el permiso
de gestión de horarios y la prohibición de cambiar indicaciones
médicas. El aviso al cuidador es informativo, sin botones, y
ninguna operación permite al cuidador confirmar o posponer
tomas.

## 7. Decisiones que quedan abiertas (con dueño y fase)

| Decisión pendiente | Por qué no se cierra en Fase 0 | Se cierra en |
|---|---|---|
| Pines exactos de versión de cada librería Python | Solo se verifican instalando y compilando | Fase 1 |
| `Dockerfile` del backend | Solo aporta si hay demo desplegada; si no, es peso muerto | Fase 9 |
| Webhook de Telegram | Solo si hay dominio público con TLS | Fase 9, si aplica |
| Zona horaria por defecto definitiva | Es un valor inicial configurable, no una regla | Fase 2 |
| Nombres y reparto final de integrantes | Los debe confirmar el equipo | Antes de la Fase 1 |
