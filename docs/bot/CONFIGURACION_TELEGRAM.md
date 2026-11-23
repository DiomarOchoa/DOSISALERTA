# Configuración de Telegram — DosisAlerta

> Sin secretos: este documento no contiene ningún token,
> contraseña ni valor real. Solo nombres de variables, comandos
> y procedimientos. Estado: Fase 6 completada (2026-11-22);
> **el token real del bot sigue pendiente** (lo pone Diomar
> vía BotFather). Sin token real no hay bot en vivo ni avisos.

## 1. Qué necesitas antes de empezar

- Una cuenta de Telegram (en el móvil o en el escritorio).
- Acceso al archivo `.env` de la raíz del proyecto (solo quien
  gestione el entorno; nunca se comparte ni se sube a Git).
- El backend en marcha (ver `docs/GUIA_INSTALACION_WINDOWS.md`).

## 2. Crear el bot en BotFather

1. En Telegram, busca **@BotFather** (el bot oficial de
   Telegram para crear bots) y pulsa **Iniciar**.
2. Escribe `/newbot` y sigue sus preguntas:
   - **Nombre visible del bot:** por ejemplo, `DosisAlerta`.
   - **Nombre de usuario del bot:** el previsto es
     `DosisAlertaBot`. Si BotFather dice que ya está en uso,
     elige otro y actualiza `TELEGRAM_BOT_USERNAME` en `.env`
     con ese nombre (sin la `@`).
3. BotFather te devolverá el **token del bot**: una cadena
   larga de letras, números y dos puntos. **Cópialo en ese
   momento y no lo pegues en ningún chat, documento ni captura.**
4. Opcional: en BotFather puedes poner una descripción y una
   foto al bot con `/setdescription` y `/setuserpic`. No es
   obligatorio para que funcione.

> El token es la llave de tu bot: quien lo tenga puede
> controlar el bot. Trátalo como una contraseña.

## 3. Poner el token y el secreto en `.env`

En la raíz del proyecto, abre `.env` (nunca `.env.example`:
ese archivo es la plantilla y no lleva valores reales) y
completa:

| Variable | Qué poner |
|---|---|
| `TELEGRAM_BOT_TOKEN` | El token que te dio BotFather, tal cual, sin comillas. Sustituye el placeholder que trae la plantilla. |
| `TELEGRAM_BOT_USERNAME` | El nombre de usuario del bot sin `@` (por defecto, `DosisAlertaBot`). |
| `TELEGRAM_LINK_SECRET` | Un secreto nuevo, distinto de `JWT_SECRET` y de `CAREGIVER_LINK_SECRET`, de al menos 32 caracteres. Si aún no existe, genéralo en PowerShell con: `python -c "import secrets; print(secrets.token_urlsafe(32))"` y pega el resultado. Nunca compartas ese valor. |

Reglas:

- Los tres secretos (`JWT_SECRET`, `CAREGIVER_LINK_SECRET`,
  `TELEGRAM_LINK_SECRET`) son obligatorios, distintos entre
  sí y de al menos 32 caracteres. El backend **no arranca**
  sin los tres.
- `TELEGRAM_BOT_TOKEN` es el único valor que viene de fuera
  (BotFather). Todo lo demás se genera en local con `secrets`.
- **Nunca** escribas el token en el código, en la
  documentación, en un chat ni en una captura de pantalla.
- Si el token se filtra (por ejemplo, se pegó por error en un
  chat), **revócalo en BotFather** con `/revoke` y pon el
  token nuevo en `.env`. El token viejo dejará de funcionar.

## 4. Arrancar el bot

El bot es un proceso aparte del backend (ver
`docs/architecture/ARQUITECTURA.md` §3): hace polling, es
decir, pregunta a Telegram si hay mensajes nuevos; no necesita
ningún servidor público.

Con el entorno virtual activado, desde `backend/`:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.bot.main
```

El bot debe arrancar sin errores y quedarse esperando
mensajes. Déjalo corriendo en su propia terminal mientras
quieras usar Telegram. Para pararlo: `Ctrl+C`.

> **El bot nunca ha corrido como proceso persistente
> todavía.** En la entrega se arranca a mano para la demo.
> No hay todavía un servicio de Windows ni un arranque
> automático: eso queda fuera del alcance de la entrega.

Comprobación rápida: abre el bot en Telegram y escribe
`/start`. Si tu chat no está vinculado, el bot te dirá que
necesitas vincular tu cuenta (ver §5). Eso significa que el
bot está vivo y respondiendo.

## 5. Vincular una cuenta

La vinculación une tu cuenta de DosisAlerta con tu chat de
Telegram. Sin ella, el bot no te muestra nada ni te obedece.

1. Genera un **código de vinculación** de 10 caracteres con
   tu sesión iniciada: `POST /api/v1/telegram/link` (en la
   documentación de la API, `http://localhost:8000/docs`, o
   con cualquier cliente HTTP). La respuesta trae el código y
   su vencimiento.
   > **Pendiente:** la web todavía no tiene un botón para
   > generar este código (Fase 8). Se genera desde la API.
2. En el chat con el bot, escribe:

   ```text
   /vincular CÓDIGO
   ```

   sustituyendo `CÓDIGO` por tu código, en el chat privado
   con el bot (nunca en un grupo).
3. El bot confirma la vinculación. El código queda usado y
   no sirve otra vez.

Reglas del código:

- Caduca en **15 minutos** y solo sirve **una vez**.
- El código en texto plano nunca se guarda: solo se guarda
  su HMAC-SHA256 con `TELEGRAM_LINK_SECRET`.
- Si acumulas **5 intentos fallidos desde el mismo chat en
  15 minutos**, se bloquean nuevos intentos desde ese chat
  durante 15 minutos.
- Ante un código inexistente, vencido, usado o bloqueado, el
  bot responde siempre lo mismo ("Código inválido o vencido"),
  para no confirmar qué códigos existen.
- Tras procesar `/vincular`, el bot intenta borrar tu mensaje
  con el código (best effort). Como el código es de un solo
  uso, uno ya usado que quedara visible no sirve para vincular.

### Vincularse como cuidador

El cuidador usa el mismo mecanismo con el código de
invitación de cuidadores (no con el código de vinculación
de Telegram): en el chat con el bot, escribe
`/vincular_cuidador CÓDIGO`. Después, el paciente aún debe
aceptar la invitación y fijar los permisos en la web
(ver `docs/MANUAL_USUARIO.md` §9).

### Consultar el estado de vinculación

Con tu sesión iniciada: `GET /api/v1/telegram/status`.
Responde `SIN_VINCULAR`, `PENDIENTE`, `VINCULADA` o
`REVOCADA`, con el nombre de usuario de Telegram y la fecha
de vinculación si la hay. Nunca devuelve el código.

## 6. Desvincular

Con tu sesión iniciada: `POST /api/v1/telegram/unlink`.

Al desvincular, la cuenta queda `REVOCADA`: el scheduler deja
de enviarte avisos y el bot deja de responder a tus mensajes
hasta que vuelvas a vincular con un código nuevo.

> **Pendiente:** la web todavía no tiene un botón para
> desvincular; se hace desde la API.

## 7. Encender el programador (avisos) solo después del token

Los avisos los envía **solo el programador** (scheduler), que
corre dentro del proceso de la API. El bot nunca envía
recordatorios por su cuenta.

- Por defecto el programador está **apagado**
  (`SCHEDULER_ENABLED=false`). Así debe seguir mientras no
  haya token real: con el placeholder no se puede enviar nada
  y no debe intentarse.
- **Solo después** de poner el token real en `.env`, pon
  `SCHEDULER_ENABLED=true` en `.env` y reinicia el backend.
  A partir de ahí, a la hora de cada toma, el programador
  enviará el aviso al chat vinculado, con los botones
  **✅ YA LO TOMÉ** y **⏰ RECORDARME DESPUÉS**.
- Los avisos a cuidadores (cuando el paciente no confirma a
  tiempo) solo llegan si el vínculo está activo y el cuidador
  tiene el permiso de recibir avisos, y llegan **sin botones**.

Para comprobar que los avisos están apagados (sin token):

- `SCHEDULER_ENABLED=false` en `.env`.
- El remitente de Telegram es nulo sin token.
- El log del programador no muestra envíos.
- Ningún recordatorio pasa a `ENVIADA`/`ENVIANDO`.

## 8. Los comandos de BotFather sin manejador

En BotFather hay **13 comandos registrados** (verificado el
2026-11-18; la lista exacta no se ha vuelto a comprobar desde
entonces). El código implementa 7: `/start`, `/help`,
`/vincular`, `/vincular_cuidador`, `/medicamentos`, `/proximas`
e `/historial` (más 29 acciones de botón y el manejador de
texto libre). Los demás comandos registrados **no tienen
manejador en el código**: si un usuario escribe uno, el bot no
hará nada útil con él.

> **Decisión pendiente de Diomar:** quitar esos comandos de
> BotFather o implementarlos. **No se inventan manejadores ni
> se presentan esos comandos como funcionales.** La cifra de
> «11 sin manejador» que aparece en informes de noviembre es
> de antes de la Fase 6 (cuando solo `/start` y `/help` tenían
> manejador); hoy son 7 los implementados y el resto sigue
> pendiente, con la lista exacta por confirmar en BotFather.

## 9. Qué NO hacer

- **Nunca** compartir el token del bot con nadie, ni pegarlo
  en un chat, un documento, una captura o un repositorio.
- **Nunca** poner el token ni ningún secreto en el código ni
  en la documentación (ni siquiera como "ejemplo").
- **Nunca** encender el programador (`SCHEDULER_ENABLED=true`)
  con el token placeholder o sin token: no enviará nada y
  dejará errores en el log.
- **Nunca** escribir el código de vinculación en un grupo de
  Telegram: solo en el chat privado con el bot.
- **Nunca** usar el mismo secreto en dos variables
  (`JWT_SECRET`, `CAREGIVER_LINK_SECRET`,
  `TELEGRAM_LINK_SECRET` deben ser distintos).
- **Nunca** prometer que un aviso se envió "exactamente una
  vez": la API de Telegram no lo permite asegurar. La
  garantía real es: entrega al menos una vez, efecto
  exactamente una vez (una toma por recordatorio) y ningún
  fallo silencioso (todo intento queda registrado).
