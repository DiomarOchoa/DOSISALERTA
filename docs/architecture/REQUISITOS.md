# REQUISITOS — DosisAlerta

Fase 0. Si un requisito cambia, se actualiza este documento y el
roadmap, no solo el código.

## 1. Requisitos funcionales

### Usuarios y autenticación

- **RF01.** Registro con nombre, correo y contraseña; inicio de sesión
  con JWT. Un usuario solo ve y modifica sus propios datos.
- **RF02.** Cierre de sesión que revoca el refresh token.
- **RF03.** Perfil con zona horaria configurable (por defecto
  `America/Bogota`, cambiable por el usuario).

### Medicamentos y tratamientos

- **RF04.** Crear, consultar, editar y desactivar medicamentos propios
  (nombre, presentación, concentración, unidad, notas).
- **RF05.** Crear tratamientos con fecha de inicio y fin opcional,
  notas y estado (`ACTIVO`, `PAUSADO`, `COMPLETADO`, `CANCELADO`).
- **RF06.** Un tratamiento puede incluir uno o varios medicamentos,
  cada uno con su dosis y sus instrucciones (tabla intermedia
  `treatment_medications`). Justificación en `MODELO_DATOS.md`.
- **RF07.** Configurar horarios por medicamento dentro del tratamiento:
  días de la semana, horas del día, intervalo en días y fecha de fin
  del horario.
- **RF08.** Cancelar o pausar un tratamiento: sus recordatorios
  pendientes se cancelan, pero el historial ya registrado se conserva.

### Recordatorios, tomas e historial

- **RF09.** Consultar próximos recordatorios, ordenados por fecha y
  hora, con medicamento, dosis y tratamiento.
- **RF10.** Calendario de tomas (por día, semana y mes en la web).
- **RF11.** Confirmar una toma desde la web o desde Telegram; la toma
  queda registrada con fecha, hora y origen (`WEB` o `TELEGRAM`).
- **RF12.** Posponer un recordatorio (15, 30 o 60 minutos): el original
  queda como `POSPUESTA` y se crea uno nuevo hijo del anterior.
- **RF13.** Consultar el historial completo de tomas, incluidas las
  perdidas y las pospuestas, sin que desaparezca al modificar o
  cancelar un tratamiento.
- **RF14.** Estadísticas de cumplimiento: porcentaje de tomas a tiempo
  sobre tomas programadas, por medicamento y por periodo, excluyendo
  del denominador las canceladas por cancelación del tratamiento.

### Telegram

- **RF15.** Vinculación por código de un solo uso (10 caracteres
  con `secrets`, HMAC-SHA256 con secreto dedicado, vencimiento de
  15 minutos, 5 fallos por `chat_id` en 15 minutos, mensaje genérico
  ante cualquier fallo) y desvinculación desde la web.
- **RF16.** Bot con menú por botones: medicamentos, próximos
  recordatorios, historial y cancelación de tratamientos.
- **RF17.** Notificaciones automáticas a la hora programada, con
  botones **Tomada** y **Posponer**.
- **RF18.** Crear y modificar medicamentos y tratamientos desde el bot,
  con los mismos servicios y validaciones que la web.
- **RF19.** El bot rechaza cualquier comando de un `chat_id` no
  vinculado, sin revelar datos de otros usuarios.

## 2. Requisitos no funcionales

- **RNF01. Seguridad:** contraseñas bcrypt, JWT con expiración,
  secretos solo en `.env`, aislamiento por usuario en cada consulta
  **y** FK compuestas `(padre_id, user_id)` en la BD como red de
  seguridad contra asociaciones entre cuentas (ver
  `MODELO_DATOS.md` §7).
- **RNF02. Persistencia confiable:** PostgreSQL como única fuente de
  verdad; ninguna información vive solo en memoria, en el frontend o
  en el bot.
- **RNF03. Disponibilidad del aviso:** un reinicio del servidor no
  pierde recordatorios pendientes; los ya enviados con
  `telegram_message_id` no se reenvían; y un intento ambiguo queda
  registrado como `AMBIGUA` y se decide en reconciliación, nunca se
  inventa como enviado (ver motor en `ARQUITECTURA.md` §7 y
  `MODELO_DATOS.md` §9). La garantía es entrega al menos una vez y
  efecto exactamente una vez, no envío exactamente una vez, porque
  la API de Telegram no lo permite asegurar.
- **RNF04. Tiempo correcto:** todos los instantes se guardan en UTC
  (`timestamptz`); las horas de horario son horas de pared y las
  fechas son fechas de calendario en la zona IANA del usuario. Los
  cambios de horario de verano se resuelven con reglas explícitas
  (hora inexistente: desplazar a la primera válida; hora ambigua:
  primera ocurrencia) y cambiar de zona recalcula solo los
  `PENDIENTE` futuros (ver `MODELO_DATOS.md` §8).
- **RNF05. Rendimiento razonable:** la consulta de próximos
  recordatorios y del historial debe responder con índices (ver
  `MODELO_DATOS.md`), no con recorridos completos de tabla.
- **RNF06. Usabilidad:** la web y el bot deben poder usarse sin leer
  un manual: etiquetas claras, botones con la acción escrita y errores
  en lenguaje normal, no códigos internos.
- **RNF07. Mantenibilidad:** código modular por dominio, pruebas
  automatizadas y documentación que permita defender cada decisión en
  10 minutos de sustentación.
- **RNF08. Privacidad:** los datos de salud (qué toma cada usuario)
  no se exponen en logs, URLs ni mensajes de error, y nunca se envían
  a un tercero distinto de Telegram (el canal que el usuario vinculó).

## 3. Casos de uso principales

| ID | Caso de uso | Actor | Resultado |
|---|---|---|---|
| CU01 | Registrarse e iniciar sesión | Usuario web | Sesión JWT válida |
| CU02 | Crear medicamento y tratamiento con horarios | Usuario web o Telegram | Horarios y recordatorios generados |
| CU03 | Consultar próximos recordatorios | Usuario web o Telegram | Lista ordenada por hora |
| CU04 | Recibir aviso y confirmar la toma | Usuario Telegram | Toma registrada, origen TELEGRAM |
| CU05 | Posponer un aviso | Usuario Telegram o web | Nuevo recordatorio hijo, anterior POSPUESTA |
| CU06 | Consultar historial y cumplimiento | Usuario web o Telegram | Tomas, perdidas y porcentaje |
| CU07 | Cancelar un tratamiento | Usuario web o Telegram | Pendientes cancelados, historial intacto |
| CU08 | Vincular / desvincular Telegram | Usuario web + bot | Cuenta vinculada o revocada |
| CU09 | Recuperar recordatorios tras un reinicio | Sistema (scheduler) | Pendientes recargados, enviados no reenviados, ambiguos reconciliados |

## 4. Cumplimiento de los requisitos oficiales de la asignatura

Estado en la Fase 0. "Previsto" significa diseñado y asignado a una
fase, no cumplido todavía; no se marca como cumplido lo que no existe.

| Requisito oficial | Estado en Fase 0 | Evidencia / fase que lo cierra |
|---|---|---|
| 1. Aplicación real en Python | Diseñado, stack fijado | Backend Python en Fases 1–9 |
| 2. Interfaz o punto de acceso real | Diseñado (web + bot) | Fases 6 y 8 |
| 3. Persistencia de información | Diseñado (PostgreSQL) | Fase 2 |
| 4. Integración con servicios externos | Diseñado (Telegram Bot API) | Fase 6 |
| 5. Funcionalidades verificables | Definidas (RF01–RF19) | Pruebas por fase en ROADMAP |
| 6. Código modular y organizado | Estructura definida | Fase 1 |
| 7. Separación lógica / presentación | Capas definidas | Fases 1–4 |
| 8. Variables sensibles en `.env` | Cumplido en diseño | `.env.example` + `.gitignore`; verificación en Fase 1 |
| 9. `requirements.txt` o `pyproject.toml` | Decidido: `pyproject.toml` | Fase 1 (sin duplicado) |
| 10. `.gitignore` correcto | Creado | `.gitignore` (Python, Node, `.env`) |
| 11. README completo | Creado (esta fase) | `README.md`, con Uso de IA |
| 12. Documentación del uso de IA | Creado | Sección "Uso de IA" en `README.md` |
| 13. Repositorio Git público | **Publicado** | https://github.com/DiomarOchoa/DOSISALERTA, rama `main`, commit inicial `2bc7ec8` (2026-11-04), 51 archivos; el push se hizo tras aprobar la Fase 1 |
| 14. Mínimo 5 commits por integrante | **Pendiente** | Reparto en ROADMAP; empieza en Fase 1 |
| 15. Sustentación presencial de 10 min | Preparación prevista | Guion y ensayo en Fase 9 |
| Entrega 25 nov 2026, 12:00 m | Calendario propuesto | ROADMAP §2 |
