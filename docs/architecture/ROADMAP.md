# ROADMAP — DosisAlerta

Fase 0. Ninguna fase se da por terminada sin sus pruebas y su criterio
de aceptación. "Funciona en mi máquina sin probar" no es aceptación.

## 1. Convención de commits (obligatoria desde la Fase 1)

```
feat:     nueva funcionalidad
fix:      corrección de un error
docs:     solo documentación
refactor: cambio interno sin cambiar comportamiento
test:     pruebas nuevas o corregidas
build:    dependencias, Docker, configuración de construcción
style:    formato, sin cambio de lógica
```

Ejemplos: `feat: initialize fastapi backend`,
`feat: implement medication management`,
`feat: integrate telegram bot`,
`test: add reminder scheduling tests`,
`docs: update project documentation`.

**Reparto para el requisito de 5 commits por integrante (propuesta,
sin nombres inventados):** cada integrante firma un módulo y sus
pruebas (por ejemplo: autenticación, medicamentos/tratamientos,
motor de recordatorios, bot, frontend/estadísticas). Un commit que
toque el módulo de otro se hace con revisión de su dueño. El conteo
se revisa en la Fase 9 antes de entregar; si alguien va por debajo de
5, se le asignan tareas reales de su módulo, nunca commits vacíos.

**No se hacen commits automáticos ni por fuera del equipo.** La Fase 0
termina deliberadamente sin commits: el equipo revisa primero.

## 2. Calendario propuesto hasta la entrega (25 nov 2026, 12:00 m)

Propuesta, no promesa: si una fase se retrasa, se recorta pulido de
la web, nunca persistencia, seguridad ni pruebas del motor.

| Fase | Fechas propuestas | Entregable que se puede mostrar |
|---|---|---|
| 0. Fundación | 4 nov | Esta documentación |
| 1. Entorno y backend | Realizada 4 nov (propuesta 5–7 nov) | API `/health` + 1 test en verde (BD pendiente de verificar) |
| 2. Modelos y BD | 8–10 nov | Migraciones Alembic aplicadas |
| 3. Autenticación | 11–12 nov | Registro, login JWT y ruta protegida |
| 4. Medicamentos y tratamientos | 13–15 nov | CRUD con horarios y recordatorios generados |
| 5. Motor de recordatorios | 16–18 nov | Envío real con efecto único y sin fallos silenciosos tras reinicio |
| 6. Bot de Telegram | 19–20 nov | Vincular, confirmar y posponer desde Telegram |
| 7. Historial y estadísticas | 21 nov | Historial y % de cumplimiento |
| 8. Web React | 22–23 nov | Todas las vistas funcionando contra la API |
| 9. Pruebas, despliegue y docs | 24 nov | Suite en verde, guion y ensayo de 10 min |
| Entrega | 25 nov, mañana | Solo entrega. No se desarrolla. |

## 3. Fases en detalle

### FASE 0 — Fundación y arquitectura (esta fase)

- Objetivos: decidir stack, arquitectura, modelo de datos, motor,
  roadmap y documentación, sin código funcional.
- Archivos: todos los listados en `ESTADO_PROYECTO.md`.
- Pruebas: revisión cruzada de documentos (que ningún documento
  contradiga a otro) y auditoría de la Fase 0.
- Aceptación: README con Uso de IA, modelo de datos completo,
  decisiones justificadas, y este roadmap. Sin Fase 1 iniciada.
- Commits sugeridos: ninguno todavía (revisión pendiente).

### FASE 1 — Configuración del entorno y backend Python

- Objetivos: proyecto Python que arranca y se puede probar.
- Tareas: `pyproject.toml` con dependencias fijadas (incluido
  `tzdata` para `zoneinfo` en Windows); entorno virtual;
  `app/main.py` con FastAPI; configuración por `.env` con
  python-dotenv y Pydantic; `GET /health`; CORS; `docker compose up
  -d postgres` ejecutado y registrado; esqueleto Vite + React +
  TypeScript (sin vistas de negocio); primer test Pytest; clonar
  desde https://github.com/DiomarOchoa/DOSISALERTA. Nota de cierre:
  el primer push se hizo en realidad tras aprobar la Fase 1, no la
  Fase 0: commit `2bc7ec8` en `main`, 51 archivos, 2026-11-04.
  Segundo commit `77d0d5c` (auditoría, 7 archivos, 2026-11-04).
  Fase 1 realizada en realidad el 2026-11-04, un día antes de lo
  propuesto. Queda pendiente de esa tarea original: `docker compose
  up -d postgres` ejecutado y registrado, y `pg_isready`
  verificado. Ese pendiente debe cerrarse antes del trabajo de
  base de datos de la Fase 2.
- Archivos: `backend/pyproject.toml`, `backend/app/main.py`,
  `backend/app/core/`, `backend/app/config/`, `frontend/package.json`.
- Pruebas: `pytest` en verde; `/health` responde 200; la BD responde
  a `pg_isready` (esta última, todavía pendiente, ver arriba).
- Aceptación: cualquier integrante puede clonar, instalar y levantar
  API + BD siguiendo el README, sin pasos no documentados.
  Aceptación parcialmente pendiente: API y tests cumplidos; BD
  pendiente de verificar, así que no se afirma que PostgreSQL
  funcione hasta que `pg_isready` se ejecute de verdad.
- Commits: `build: initialize python project`,
  `feat: initialize fastapi backend`, `test: add health check test`,
  `docs: document setup instructions`.

### FASE 2 — Modelos, entidades y base de datos

- Objetivos: esquema real en PostgreSQL, con migraciones.
- Tareas: modelos SQLAlchemy según `MODELO_DATOS.md` y
  `docs/database/RELACIONES_CUIDADORES.md`; migraciones Alembic
  (nunca `create_all` como mecanismo de evolución); datos semilla
  solo para desarrollo, fuera de migraciones de producción.
  **Cuidadores (aprobado v1, 2026-11-11):** las relaciones y
  restricciones de `caregiver_links` y `caregiver_audit_log` se
  definen antes de la migración inicial; el modelo pasa de 11 a
  14 tablas (las 11 originales no cambian). La migración inicial
  crea 13 tablas; `caregiver_link_attempts` (tabla 14, antifraude)
  queda diseñada ahora y se migra en la Fase 6 (ver F6).
- Archivos: `backend/app/models/`, `backend/app/database/`,
  `backend/alembic/versions/`.
- Pruebas: migraciones aplicadas desde cero y reversibles al menos un
  paso; restricciones únicas e índices verificados.
- Aceptación: `alembic upgrade head` crea las 13 tablas de la
  migración inicial con sus restricciones; un intento de duplicar
  `(schedule_id, scheduled_at)` falla por restricción, no por
  código; y un intento de cruzar cuentas (tratamiento de A con
  medicamento de B) falla por FK compuesta, no por código. Un
  vínculo de cuidador con `patient_user_id = caregiver_user_id`
  falla por CHECK, y dos vínculos no revocados para la misma
  pareja fallan por el índice único parcial. (`caregiver_link_attempts`
  no entra en esta aceptación: se migra en la Fase 6.)
- Commits: `feat: implement database models`,
  `feat: add initial alembic migration`, `test: add model constraint tests`.
- Estado (2026-11-11): COMPLETADA, sin commit todavía (la
  autorización de la Fase 2 no incluye commits ni push). Migración
  inicial `f2a17166bccd` aplicada en PostgreSQL local (13 tablas);
  31 pruebas de modelos contra PostgreSQL real en verde;
  `alembic revision --autogenerate` sin diferencias. Puerto de
  PostgreSQL cambiado a 5433 en `.env` por conflicto con un
  PostgreSQL 18 nativo en el 5432 (ver `docs/ENTORNO_LOCAL.md`).

### FASE 3 — Autenticación y seguridad

- Objetivos: solo el dueño ve sus datos.
- Tareas: registro y login; hash bcrypt; JWT access + refresh con
  hash en `refresh_tokens`; dependencia `current_user`; manejo
  centralizado de errores; revocación al cerrar sesión.
  **Autorización (cuidadores, v1):** el `current_user` es el actor
  de cada operación; cuando actúa como cuidador, el servicio
  resuelve el vínculo en `caregiver_links` y exige vínculo
  `ACTIVO` y el permiso concreto de la operación.
- Archivos: `backend/app/api/routers/auth.py`,
  `backend/app/services/auth_service.py`, `backend/app/core/security.py`.
- Pruebas: registro duplicado (409), login con contraseña incorrecta
  (401), ruta protegida sin token (401), recurso de otro usuario (403),
  refresh revocado (401).
- Aceptación: ninguna ruta de negocio responde sin token válido, y
  ninguna consulta olvida el filtro por `user_id`.
- Commits: `feat: implement user registration`,
  `feat: implement jwt authentication`, `test: add auth security tests`.

### FASE 4 — Gestión de medicamentos y tratamientos

- Objetivos: el núcleo de negocio funciona por API.
- Tareas: CRUD de medicamentos; tratamientos con varios medicamentos;
  horarios y recurrencias; generación de recordatorios para 7 días;
  pausar/cancelar con conservación del historial.
  **Control de propiedad y permisos del cuidador (v1):** cada
  servicio valida propiedad por `user_id` y, para el cuidador,
  vínculo `ACTIVO` + permiso independiente (RF20–RF22). El
  cuidador nunca escribe en `treatment_medications` (dosis) ni
  cambia el estado de un tratamiento: el servicio lo rechaza
  siempre (403).
- Archivos: routers y servicios de `medications`, `treatments`,
  `schedules`, `reminders` (generación, no envío todavía).
- Pruebas: crear tratamiento con 2 medicamentos y horarios distintos;
  cancelar no borra tomas; horario inválido (fin antes de inicio) es 400.
- Aceptación: desde Swagger (`/docs`) se puede crear un tratamiento
  completo y consultar sus próximos recordatorios.
- Commits: `feat: implement medication management`,
  `feat: implement treatment management`,
  `feat: implement schedule generation`, `test: add treatment tests`.

### FASE 5 — Motor avanzado de recordatorios

- Objetivos: el aviso llega a la hora, una sola vez, incluso tras un
  reinicio. Es la fase que demuestra Programación Avanzada.
- Tareas: `ReminderHeap` propio (heap binario) + interfaz con respaldo
  `heapq`; índices dict por id y por usuario; tarea scheduler en el
  lifespan de la API; reclamación transaccional con
  `current_attempt_id`; envío por la API de Telegram con
  `telegram_message_id` guardado; registro de cada intento en
  `notification_logs` (`attempted_at` siempre, `sent_at` solo si
  Telegram confirma); aviso al cuidador autorizado
  (`perm_receive_notifications`, vínculo `ACTIVO`, Telegram propio
  vinculado) cuando el paciente no confirma en la ventana de
  gracia; recuperación al arrancar por reconciliación
  (no reenvío ciego de `ENVIANDO` viejos, marcar `PERDIDA` fuera de
  gracia); ventana de gracia 30 min y reintentos con backoff (máx. 3
  fallos claros, máx. 3 ambiguos).
- Archivos: `backend/app/scheduler/`, `backend/app/algorithms/`,
  `backend/app/services/reminder_service.py`.
- Pruebas: heap contra `heapq` (propiedades: orden, inserción,
  extracción, borrado perezoso); no duplicar el envío tras reclamar
  dos veces en paralelo; tras reinicio simulado, pendientes recargados
  y `ENVIADA` no reenviados; vencidos fuera de gracia marcados
  `PERDIDA`; fallo claro simulado termina `FALLIDA` tras 3 intentos
  y queda registrado; respuesta perdida simulada queda `AMBIGUA` y la
  reconciliación decide con un único reintento; confirmar dos veces
  crea una sola toma.
- Aceptación: **criterio duro corregido** — entrega al menos una vez
  y efecto exactamente una vez: en escenario normal el aviso se envía
  una vez con `telegram_message_id`; tras reinicio no se reenvían los
  enviados; ningún fallo queda en silencio (todo intento está en
  `notification_logs`); y ninguna toma se duplica aunque el mensaje
  llegue duplicado por un caso ambiguo. Si falla uno, la fase no
  está terminada aunque el resto funcione. No se exige envío
  exactamente una vez, porque la API de Telegram no lo permite asegurar.
- Commits: `feat: implement reminder priority queue`,
  `feat: implement reminder scheduler`,
  `feat: implement duplicate prevention`,
  `test: add reminder scheduling tests`.

### FASE 6 — Integración completa del bot de Telegram

- Objetivos: Telegram hace lo mismo que la web, con los mismos servicios.
- Tareas: bot con @BotFather (token solo en `.env`); proceso
  `python -m app.bot.main` en polling; `/start`, `/vincular`,
  `/medicamentos`, `/proximas`, `/historial`; botones YA LO TOMÉ y
  RECORDARME DESPUÉS (el botón NO LO HE TOMADO está eliminado
  definitivamente, 2026-11-11); creación y modificación desde el
  bot; rechazo de `chat_id` no vinculados.
  **Pacientes y cuidadores (v1):** vinculación segura por código
  de un solo uso + aceptación explícita del paciente, gestión de
  permisos individuales y revocación desde el bot (ver
  `docs/ESPECIFICACION_BOT_TELEGRAM.md` §4). Migración Alembic
  de `caregiver_link_attempts` (tabla 14, diseñada en la Fase 2):
  cada intento de código se registra en ella antes de validar.
- Archivos: `backend/app/bot/`, `backend/app/api/routers/telegram_link.py`.
- Pruebas: vincular con código válido e inválido; confirmar desde el
  botón crea la toma visible por API; posponer crea el hijo; un
  `chat_id` no vinculado no obtiene datos.
- Aceptación: una toma confirmada en Telegram aparece en la API web
  sin ninguna acción adicional, y viceversa.
- Commits: `feat: integrate telegram bot`,
  `feat: implement telegram linking`,
  `feat: implement telegram inline actions`, `test: add bot handler tests`.

### FASE 7 — Historial y estadísticas

- Objetivos: el usuario ve qué cumplió y qué perdió.
- Tareas: historial filtrable por periodo y medicamento; porcentaje
  de cumplimiento (tomas a tiempo / programadas, excluidas las
  canceladas por cancelación); calendario de tomas en la API.
  **Identificación de actor:** el historial distingue las acciones
  realizadas por el paciente de las realizadas por un cuidador
  (actor en `caregiver_audit_log`), y el paciente puede ver quién
  hizo qué sobre sus datos.
- Archivos: `backend/app/services/stats_service.py`,
  `backend/app/api/routers/stats.py`.
- Pruebas: un tratamiento con 10 programadas, 7 tomadas, 2 perdidas y
  1 cancelada por cancelación da 70 %, no 77 % ni 63 %; el historial
  sobrevive a la cancelación del tratamiento.
- Aceptación: las cifras de la API coinciden con un conteo manual
  sobre los datos de prueba.
- Commits: `feat: implement intake history`,
  `feat: implement compliance statistics`, `test: add statistics tests`.

### FASE 8 — Aplicación web completa (React)

- Objetivos: todas las vistas contra la API real, sin datos falsos.
- Tareas: login/registro; medicamentos; tratamientos; calendario;
  próximos recordatorios; historial; estadísticas; ajustes y
  vinculación de Telegram; manejo de errores y estados de carga.
- Archivos: `frontend/src/pages/`, `components/`, `services/`,
  `context/`, `hooks/`, `styles/`.
- Pruebas: flujo manual guiado (checklist en la fase) + pruebas de
  los servicios de API si se añaden; ninguna vista con datos
  hardcodeados.
- Aceptación: un usuario nuevo puede, solo con la web, registrarse,
  crear un tratamiento, ver su próximo recordatorio y vincular Telegram.
- Commits: `feat: implement web login and medications`,
  `feat: implement web treatments and calendar`,
  `feat: implement web history and statistics`, `style: polish web layout`.

### FASE 9 — Pruebas, seguridad, Docker y despliegue

- Objetivos: entregar algo defendible en 10 minutos, no algo a medias.
- Tareas: suite Pytest completa en verde; revisión de secretos
  (ningún `.env` ni token en Git, `git log` revisado); `Dockerfile`
  del backend solo si aporta a la demo (si no, documentar por qué no);
  guion de sustentación de 10 minutos con demo en vivo (web + bot);
  ensayo con preguntas difíciles; actualización final de README y
  ESTADO_PROYECTO; verificación de commits por integrante.
- Archivos: `docker/Dockerfile` (si se decide), `docs/presentation/`,
  README y ESTADO actualizados.
- Pruebas: suite completa; checklist de entrega (requisitos oficiales
  1–15, uno por uno). **Auditoría de seguridad, privacidad y
  permisos:** pruebas de acceso cruzado entre pacientes, de
  permisos del cuidador (lectura y gestión por separado, denegado
  sin permiso), de revocación inmediata y de auditoría de acciones
  del cuidador; revisión de que ningún dato de salud va en logs.
- Aceptación: el equipo puede hacer la demo completa sin depender de
  la memoria de una sola persona, y cada integrante explica su módulo.
- Commits: `test: finalize test suite`, `docs: finalize presentation`,
  `build: add production dockerfile` (si aplica).

### FASE 10 (PROPUESTA, POST-ENTREGA) — Módulo de IA

> Nota añadida el 2026-11-11 solo como documentación. No modifica
> las Fases 0–9 ni sus fechas. La Fase 8 vigente es la web React
> (22–23 nov) y no cabe en ella el módulo de IA sin recortar la web
> o retrasar la entrega del 25 de noviembre.

- Decisión oficial del equipo (2026-11-11): arquitectura híbrida,
  Google Gemini API + Ollama local, con cinco funcionalidades
  aprobadas (asistente conversacional, explicaciones sencillas,
  asistente para familiares y cuidadores, resúmenes del historial,
  preguntas frecuentes inteligentes).
- Diseño completo en `docs/architecture/MODULO_IA.md`:
  `AIService`, `AIProvider`, `GeminiProvider`, `OllamaProvider`,
  `AIProviderRouter`, `PromptManager`, `AIContextBuilder`,
  `AIResponseValidator` y `AIUsageTracker`.
- Reglas: la IA es opcional y nunca bloquea recordatorios,
  tratamientos ni demás funciones esenciales; no ejecuta acciones
  médicas; el contexto clínico solo va a Ollama local salvo
  autorización explícita; sin nuevas tablas ni columnas en la
  Fase 2.
- Esta fase empieza después de la entrega del 25 de noviembre.
  **No forma parte de los compromisos de la entrega académica ni
  de la sustentación**: nada de F1–F9 depende de ella y no se
  evalúa el 25 de noviembre. Si el equipo decide adelantarla,
  debe decidir explícitamente qué se recorta y actualizar este
  roadmap en consecuencia.
