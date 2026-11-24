# Guion de sustentación — DosisAlerta (10 minutos)

> Sustentación presencial, 10 minutos, con demo en vivo (web +
> bot). Estado: Fases 1–8 completadas, Fase 9: auditoría local completada; despliegue realizado
> (2026-11-22). Entrega del proyecto: 25 de noviembre de 2026,
> 12:00. Este guion no inventa datos: la demo usa las cuentas
> de prueba documentadas y la parte del bot depende del token
> real (ver §2, ramas con/sin token).

## 1. Estructura minuto a minuto

| Minutos | Bloque | Quién | Qué se dice / se muestra |
|---|---|---|---|
| 0:00–0:45 | Problema | Diomar | Qué problema resuelve DosisAlerta y para quién. |
| 0:45–3:30 | Demo web en vivo | Diomar + Maisha | Login, medicamentos, crear tratamiento, próxima toma, historial, estadísticas, calendario. |
| 3:30–4:30 | Demo bot | Diomar | Vinculación, comandos, confirmar desde el botón. Con token: en vivo. Sin token: código + pruebas (ver §2). |
| 4:30–5:30 | Arquitectura | Diomar | Monolito modular, dos procesos, una sola BD, el servicio manda. |
| 5:30–6:30 | Decisiones D-1 a D-11 | Roderic | Las 11 decisiones de la Fase 7, una frase cada una (§4). |
| 6:30–7:15 | Seguridad y cuidadores | Jaider | JWT, aislamiento por usuario, permisos de cuidador y auditoría. |
| 7:15–8:15 | Pruebas y calidad | Roderic + Maisha | Suite 564 + 1 fallo conocido, harnesses 7/7, defecto corregido. |
| 8:15–9:30 | Limitaciones honestas | Diomar | RF15 sin UI web, RF18 parcial, token pendiente, programador apagado. |
| 9:30–10:00 | Cierre | Diomar | Qué se entrega, qué sigue (Fase 10, IA) y preguntas. |

**Regla de tiempo:** si la demo se alarga, se recorta la demo
del bot, nunca las limitaciones: una sustentación que esconde
lo incompleto pierde más que una demo corta.

## 2. Guion de la demo en vivo

### 2.1. Antes de empezar (preparación)

- Backend en marcha (`uvicorn`, puerto 8000) y frontend en
  marcha (`npm run dev`, puerto 5173). PostgreSQL en Docker
  (puerto 5433 en el PC del equipo).
- Navegador abierto en `http://localhost:5173`.
- Cuentas de prueba documentadas (no se crean credenciales
  nuevas para la demo):
  - **Cuenta principal:** `prueba-entrega1-20261120@gmail.com`,
    contraseña `Prueba1234`. Tiene 7 medicamentos activos, 3
    inactivos, historial con decenas de registros y varios
    tratamientos. Zona horaria `America/Bogota`.
  - **Cuenta vacía:** `prueba-entrega1-c-20261120@gmail.com`,
    contraseña `Prueba1234`. Sin medicamentos ni tratamientos.
- El bot: ver la rama con/sin token más abajo.

### 2.2. Demo web (2:45, cuenta principal)

1. **Login (0:15).** Entra con la cuenta principal. "Aquí
   estamos dentro: el token dura 60 minutos y se renueva con
   el refresh de 7 días; al salir, el refresh se revoca."
2. **Panel `/inicio` (0:20).** "La próxima toma, las acciones
   rápidas y el estado de las fases." Señala la próxima toma
   (si la hay) y el enlace "Ver tratamiento".
3. **Medicamentos (0:20).** Abre `/medicamentos`. "7 activos,
   3 inactivos." Abre un inactivo y pulsa **Reactivar**…
   y vuelve a desactivarlo, o mejor: **no toques los datos
   reales en la demo**; muestra el botón y explica que
   reactivar no resucita las tomas canceladas.
4. **Crear un tratamiento en vivo (0:45).** "Esto es lo que
   un usuario hace de verdad." Crea un tratamiento llamado
   `Demo sustentación` con fecha de hoy, añade un medicamento
   del catálogo con dosis 1 tableta y un horario diario a una
   hora de dentro de 10 minutos. Guarda y ve a
   `/recordatorios`: la toma aparece en "Próximas tomas".
   (Las tomas se generan para las próximas 72 horas; una hora
   de dentro de 10 minutos aparecerá de inmediato.)
5. **Confirmar y posponer (0:20).** Confirma la toma recién
   creada con **Tomada**… o mejor: posponla 15 minutos para
   mostrar el hijo que se crea, y luego confirma el hijo.
   "La original queda POSPUESTA, el hijo es la toma real, y
   el historial conserva las dos."
6. **Historial y estadísticas (0:30).** Abre `/historial`:
   filtra por TOMADA y muestra que cada fila dice qué pasó,
   cuándo y desde dónde. Abre `/estadisticas`, cambia el
   grupo a "por medicamento" y explica el porcentaje: "las
   canceladas con motivo conocido no bajan el porcentaje;
   las de motivo desconocido sí cuentan" (decisión D-11).
7. **Calendario y perfil (0:15).** Abre `/calendario` (mes y
   semana) y `/perfil`: "aquí se cambia la zona horaria; solo
   se recalculan las pendientes futuras".

> Si la cuenta principal no tiene próximas tomas en ese
> momento (el programador está apagado y las tomas se
> consumen al verificar), el paso 4 es el que genera una:
> crear el tratamiento en vivo es la forma fiable de mostrar
> una próxima toma. No digas que "siempre hay tomas": di
> que las tomas se generan para las próximas 72 horas.

### 2.3. Demo bot (1:00)

**Con token real (si Diomar ya lo puso en `.env` y el bot
está corriendo con `python -m app.bot.main`):**

1. En Telegram, abre el bot y escribe `/start`: aparece el
   menú con botones.
2. Escribe `/proximas`: se ven las próximas tomas con sus
   botones. Pulsa **✅ YA LO TOMÉ** en una: el bot edita el
   mensaje ("✓ Tomada a las …").
3. Vuelve a la web, abre `/historial`: la toma aparece como
   TOMADA con origen Telegram. "Lo que se confirma en
   Telegram aparece en la web sin hacer nada más: es el
   mismo servicio y la misma base de datos."
4. Si la cuenta no está vinculada, muestra `/vincular` con un
   código generado en la API y completa la vinculación en
   vivo.

**Sin token real (situación actual a 2026-11-22):**

No hay demo en vivo del bot: sin token el proceso no arranca
y no se puede enviar ni recibir nada. En ese caso, di
exactamente esto: *"El bot está implementado y probado (7
comandos, 29 acciones de botón, 19 pruebas de flujo), pero
la demo en vivo está bloqueada porque el token real de
BotFather aún no está en el entorno. Lo que sí puedo mostrar
es el código y la prueba que confirma una toma desde el botón
y la deja visible en el historial de la API."* Y muestra:

1. El `build_application` con 37 handlers.
2. La prueba de flujo `test_bot_telegram_flows.py` (19/19)
   y su caso de aceptación: confirmar desde el botón crea la
   toma con origen TELEGRAM, visible en el historial.
3. El mensaje genérico ante código inválido (mismo texto para
   inexistente, vencido, usado o bloqueado).

No finjas una demo del bot con capturas de otro sistema ni
con datos simulados: si no hay token, se dice y se muestra
la evidencia de pruebas.

### 2.4. Qué NO mostrar

- No muestres `.env`, tokens ni secretos en pantalla.
- No muestres la base de datos con contraseñas (hashes).
- No presentes como funcional un comando de BotFather sin
  manejador (son 11; decisión pendiente de Diomar).
- No digas que los avisos llegan si el programador está
  apagado: sin token no hay avisos en vivo.

## 3. Arquitectura (1:00, Diomar)

- "Un monolito modular en Python con FastAPI: dos procesos
  (API + bot) que comparten los mismos servicios y la misma
  base de datos PostgreSQL, y dos canales (web React y bot
  de Telegram). No hay lógica de negocio duplicada: el
  servicio manda, el canal solo traduce."
- "El programador vive en la API y es el único que envía
  avisos. El bot nunca envía recordatorios por su cuenta."
- "Aislamiento por usuario en dos capas: el servicio filtra
  por `user_id` y la base de datos lo refuerza con claves
  foráneas compuestas `(padre_id, user_id)`."
- "Todo instante en UTC; las horas de horario son horas de
  pared y las fechas son fechas de calendario en la zona del
  usuario."

## 4. Decisiones D-1 a D-11 (1:00, Roderic)

Una frase por decisión (Fase 7, todas de Diomar, 2026-11-21):

- **D-1:** Las canceladas por cancelar el tratamiento quedan
  fuera del denominador del cumplimiento (ejemplo: 7 de 9
  son 77,8 %).
- **D-2:** La toma original pospuesta queda excluida de las
  cuentas.
- **D-3:** La toma fallida queda excluida de las cuentas.
- **D-4:** Por defecto, los últimos 30 días en la zona del
  paciente.
- **D-5:** Historial en `/reminders/history` y cumplimiento
  en `/stats/compliance`.
- **D-6:** Paginación con límite por defecto 50 (de 1 a 200)
  y desplazamiento sin máximo, con total y orden fijo por
  fecha y luego por id.
- **D-7:** Un solo endpoint con agrupación opcional por día,
  semana ISO (lunes a domingo), mes o medicamento, con series
  completas aunque haya periodos vacíos.
- **D-8:** La gracia de 30 minutos es inclusiva: a los 30:00
  exactos es a tiempo; a los 30:01 es tardía.
- **D-9:** Una toma confirmada sin hora registrada cuenta
  como tardía por convención, y se ve con hora y origen vacíos.
- **D-10:** El historial muestra los 8 estados, incluidas
  pendientes y futuras, solo las dosis ya generadas
  (horizonte de 72 horas) y siempre el estado guardado.
- **D-11:** Las canceladas con motivo conocido quedan fuera
  del denominador y las de motivo desconocido dentro:
  denominador = programadas − canceladas + desconocidas,
  con el motivo guardado en `cancel_reason`.

## 5. Pruebas y calidad (1:00, Roderic + Maisha)

- "Suite del backend: **564 pasadas y 1 fallo conocido
  preexistente** (un test de estructura al que se le filtra el
  token placeholder del `.env`). No es una regresión y no se
  oculta: está declarado en los informes."
- "Frontend: build en verde (83 módulos) y **7 harnesses
  jsdom en verde** contra la API real (historial,
  estadísticas, navegación, confirmar/posponer, cuidadores,
  calendario, zona horaria)."
- "Etapa 7 corrigió un defecto real de horario de verano:
  una hora inexistente se desplazaba y chocaba con la hora
  válida siguiente; ahora va a la primera hora válida, con
  prueba de reproducción. Bogotá no tiene horario de verano,
  así que ningún dato actual cambió."
- "Etapa 7 encontró y corrigió un defecto de permisos: un
  `patient_id` inexistente daba error 500 en los 4 módulos;
  ahora da 403, con prueba de regresión. Las comprobaciones
  de acceso cruzado fueron 13 de 13 correctas."

## 6. Limitaciones honestas (1:15, Diomar)

Decirlas antes de que las pregunten:

1. **RF15 sin interfaz web:** la vinculación de Telegram
   funciona por API y por bot, pero la web no tiene todavía
   pantalla para generar el código ni para desvincular.
2. **RF18 parcial:** desde el bot se pueden crear, modificar
   y desactivar medicamentos y se pueden pausar, reanudar,
   cancelar y completar tratamientos, pero **no se puede
   crear un tratamiento desde el bot**.
3. **Token real pendiente:** sin el token de BotFather no hay
   bot en vivo ni avisos; el programador está apagado por
   defecto (`SCHEDULER_ENABLED=false`) hasta que exista.
4. **Comandos de BotFather sin manejador:** 13 registrados
   (lista exacta por confirmar); 7 implementados; decisión
   pendiente (quitarlos o implementarlos).
5. **Acceso de cuidador por `patient_id`:** verificado en
   historial y estadísticas; en medicamentos, tratamientos y
   próximas tomas está cableado por permisos, verificado en
   la Etapa 7.
6. **Comprobación visual a 390 px pendiente** en el PC.
7. **Módulo de IA:** es propuesta post-entrega (Fase 10),
   no parte de la entrega. La IA ayudó a desarrollar (ver
   `docs/architecture/MODULO_IA.md` §13); el producto no
   depende de ella.

## 7. Preguntas difíciles probables (con respuesta corta)

- **"¿Por qué no garantizan que el aviso llegue exactamente
  una vez?"** — Porque la API de Telegram no ofrece claves de
  idempotencia ni forma de verificar un envío. La garantía
  real es: entrega al menos una vez, efecto exactamente una
  vez (una toma por recordatorio, botones idempotentes) y
  ningún fallo silencioso (todo intento queda registrado).
- **"¿Qué pasa si dos personas confirman la misma toma a la
  vez?"** — Solo se crea una toma: `reminder_id` es único en
  la tabla de tomas y confirmar dos veces es idempotente.
- **"¿Cómo evitan que un cuidador vea datos de otro
  paciente?"** — Tres capas: vínculo activo + permiso
  concreto + registro del paciente vinculado; si falta algo,
  403 con auditoría. Además, la base de datos lo refuerza
  con claves foráneas compuestas. Verificado con 13
  comprobaciones de acceso cruzado.
- **"¿Por qué el fallo de la suite?"** — Es un test de
  estructura al que se le filtra el token placeholder del
  `.env` del entorno. Preexistente, conocido, declarado. No
  es una regresión de las Fases 4–9.
- **"¿Por qué no hay aplicación móvil?"** — Fuera de alcance:
  los canales exigidos son web y Telegram, y son los dos que
  se entregan.
- **"¿El porcentaje de cumplimiento no engaña?"** — No: las
  canceladas con motivo conocido no cuentan (decisión D-11),
  así que pausar un tratamiento no te baja el porcentaje; y
  una toma confirmada sin hora cuenta como tardía (D-9).
- **"¿Qué pasa con el horario de verano?"** — Hora
  inexistente: se desplaza a la primera hora válida. Hora
  ambigua: se usa la primera ocurrencia. Colombia no tiene
  horario de verano, pero el sistema no lo asume.
- **"¿Por qué no usaron Row Level Security?"** — Decisión
  documentada: servicio + claves foráneas compuestas es
  suficiente y demostrable para este tamaño; RLS con
  conexiones agrupadas añadiría una capa de fallo difícil
  de depurar.
- **"¿Y si se cae el bot?"** — La web sigue funcionando y el
  programador (que vive en la API) sigue enviando avisos. Si
  se cae la API, el bot sigue respondiendo consultas y los
  avisos se recuperan al volver.
- **"¿Quién hizo qué?"** — Diomar coordinó y llevó motor y
  bot; Jaider, autenticación y Fase 4; Roderic, Fase 7 y su
  auditoría; Maisha, el frontend de la Fase 8. Los 4 cumplen
  el requisito de 5 commits (28, 5, 5 y 5).

## 8. Reparto por integrante

| Integrante | Commits en `main` | Defiende |
|---|---|---|
| **Diomar Ochoa** (líder) | 28 | Problema, demo web, demo bot, arquitectura, limitaciones y cierre. Motor de recordatorios (Fase 5) y bot de Telegram (Fase 6). |
| **Jaider Toro Camacho** | 5 | Autenticación JWT (Fase 3) y Fase 4: cómo se aísla a cada usuario y por qué el cierre de sesión revoca el refresh. |
| **Roderic Gallardo** | 5 | Fase 7: decisiones D-1 a D-11, auditoría de la Fase 7, pruebas y calidad, corrección del defecto de permisos (500 → 403). |
| **Maisha** | 5 | Frontend de la Fase 8 (Entregas 0–4): autenticación en la web, medicamentos, historial y estadísticas en React, y cómo se verifica sin tests unitarios (harnesses jsdom). |

Si el profesor pregunta a uno por el módulo de otro, la
respuesta es: "Ese módulo lo llevó [nombre]; lo que puedo
decirte es [una frase], y [nombre] te da el detalle." No
improvisar detalles de un módulo ajeno.

## 9. Cierre (0:30, Diomar)

- "DosisAlerta está entregado: web completa, bot
  implementado y probado, 564 pruebas en verde, 14 tablas,
  decisiones documentadas y limitaciones declaradas."
- "Lo que queda pendiente depende de una sola cosa que solo
  yo puedo desbloquear: el token real de BotFather. Con él,
  el bot arranca y los avisos se encienden."
- "Después de la entrega, la propuesta es la Fase 10: el
  módulo de IA (asistente, explicaciones y resúmenes), sin
  tocar el núcleo."
- Gracias y preguntas.
