# Manual de usuario — DosisAlerta

> Para el paciente y para el cuidador. En español claro, sin
> jerga técnica. Estado: Fases 1–8 completadas (2026-11-22).
> Entrega del proyecto: 25 de noviembre de 2026, 12:00.

## 1. Qué es DosisAlerta

DosisAlerta te ayuda a no olvidar tus medicamentos. Tú registras
tus medicamentos y tus tratamientos con sus horarios; la
aplicación te muestra qué debes tomar y cuándo, te avisa por
Telegram a la hora de cada toma (cuando los avisos estén
activados), y guarda un historial de todo lo que pasó con cada
toma: si la tomaste a tiempo, tarde, si la pospusiste o si se
te pasó.

Puedes usarla por la **web** (en el navegador) y por **Telegram**
(con el bot). Lo que haces en un canal se ve en el otro: si
confirmas una toma en Telegram, aparece en la web, y al revés.

> **Importante:** DosisAlerta no sustituye a tu médico. No
> cambies dosis ni suspendas tratamientos desde aquí sin
> hablar con él: la aplicación registra lo que tu médico te
> indicó y te ayuda a seguirlo.

## 2. Registro e inicio de sesión

### Crear tu cuenta

1. Abre la web y pulsa **Registrarse**.
2. Escribe tu nombre, tu correo y una contraseña.
3. Elige tu zona horaria (por defecto, `America/Bogota`).
   La zona horaria importa: tus horarios se entienden en la
   hora de donde vives.
4. Pulsa el botón de registro. Quedarás dentro, en el panel
   principal.

### Entrar

1. Abre la web y escribe tu correo y tu contraseña.
2. Pulsa **Entrar**.

### Salir

Pulsa **Salir** en la cabecera. Al salir, tu sesión se cierra
también en el servidor: nadie podrá usar tu sesión desde ese
navegador.

### Si olvidas tu contraseña

> **Pendiente:** la aplicación todavía no tiene botón de
> "olvidé mi contraseña" ni de cambio de contraseña. Si
> olvidas tu contraseña, avisa al responsable del proyecto.

## 3. Medicamentos

Un medicamento es tu catálogo personal: por ejemplo,
"Amoxicilina 500 mg". Existe aunque no esté en ningún
tratamiento activo, y puedes reutilizarlo en otro tratamiento
después.

### Crear un medicamento

1. Ve a **Medicamentos** y pulsa el botón para crear uno nuevo.
2. Escribe el nombre (obligatorio) y, si quieres, la
   presentación (tableta, jarabe, cápsula…), la concentración
   (por ejemplo, "500 mg"), la unidad (por ejemplo,
   "tableta") y unas notas.
3. Guarda. El medicamento aparece en tu lista de activos.

### Editar un medicamento

Abre el medicamento y edita sus datos. Hay cosas que la
aplicación no te deja cambiar a la ligera: si el medicamento
está en un tratamiento activo, la concentración y la unidad
no se pueden editar desde ahí, porque forman parte de lo que
te indicó el médico.

### Desactivar un medicamento

Si dejas de tomar un medicamento, **desactívalo** en lugar de
borrarlo: así se conserva su historial. Al desactivarlo, sus
tomas pendientes futuras se cancelan y quedan registradas como
canceladas (con el motivo "medicamento desactivado").

### Reactivar un medicamento

Un medicamento desactivado aparece en la pestaña de inactivos.
Pulsa **Reactivar** y vuelve a estar disponible para nuevos
tratamientos. Las tomas que se cancelaron al desactivarlo **no**
vuelven: el historial no se reescribe.

## 4. Tratamientos y horarios

Un tratamiento es un plan: por ejemplo, "Tratamiento de 7 días
de noviembre". Tiene una fecha de inicio, una fecha de fin
opcional, uno o varios medicamentos (cada uno con su dosis y
sus instrucciones) y un horario por cada medicamento.

### Crear un tratamiento

1. Ve a **Tratamientos** y pulsa el botón para crear uno nuevo.
2. Ponle un título y una fecha de inicio (y de fin, si la sabes).
3. Añade al menos un medicamento: elige uno de tu catálogo,
   escribe la dosis (por ejemplo, 1 tableta) y las
   instrucciones (por ejemplo, "con alimentos").
4. Define el horario de cada medicamento:
   - **Todos los días**, a una o varias horas (por ejemplo,
     08:00 y 20:00).
   - **Ciertos días de la semana** (por ejemplo, lunes,
     miércoles y viernes), a una o varias horas.
   - **Cada cierto número de días** (por ejemplo, cada 2 días),
     a una hora.
5. Guarda. La aplicación genera las tomas de las próximas
   72 horas y las verás en "Próximas tomas" y en el calendario.

### Estados de un tratamiento

- **Activo:** el tratamiento está en curso y genera tomas.
- **Pausado:** no genera tomas nuevas mientras esté pausado.
  Al reanudarlo, se vuelven a generar las tomas futuras.
- **Completado:** el tratamiento terminó como estaba previsto.
- **Cancelado:** el tratamiento se dio por terminado antes de
  tiempo.

Al pausar, completar o cancelar un tratamiento, sus tomas
pendientes futuras se cancelan y quedan en el historial con
el motivo correspondiente. **El historial nunca se borra:**
cancelar no elimina lo que ya pasó.

### Qué no se puede hacer

- Un tratamiento **no se puede crear desde el bot de Telegram**:
  solo desde la web. Desde el bot sí se puede pausar,
  reanudar, cancelar o completar un tratamiento que ya existe.
- Nadie (ni siquiera un cuidador) puede cambiar la dosis
  prescrita ni las indicaciones médicas desde la aplicación.

## 5. Próximas tomas: confirmar y posponer

En el panel principal y en **Recordatorios** verás tus próximas
tomas ordenadas por hora, con el medicamento, la dosis y el
tratamiento al que pertenecen. Solo se muestran las tomas de
las próximas 72 horas: son las que ya están generadas.

### Confirmar que tomaste la dosis

Cuando tomes tu medicamento, pulsa **Tomada** en esa fila.
Queda registrada la hora exacta en que la confirmaste y desde
dónde (web o Telegram). Si la confirmas dentro de los 30
minutos siguientes a la hora programada, cuenta como
**a tiempo**; si la confirmas después de esos 30 minutos,
cuenta como **tardía**. Exactamente a los 30 minutos todavía
es a tiempo.

### Posponer una toma

Si no puedes tomarla ahora, pulsa **Posponer** y elige 15, 30
o 60 minutos. La toma original queda marcada como pospuesta y
se crea una nueva toma a la hora elegida. Puedes posponer una
misma toma como máximo **3 veces** seguidas; a la cuarta, la
aplicación no te dejará posponerla más.

> **No existe el botón "NO LO HE TOMADO".** Si no tomas la
> dosis, simplemente no la confirmes: cuando pase su hora más
> los 30 minutos de gracia, quedará registrada como perdida.
> No hay que pulsar nada para decir que no la tomaste.

### Si se te pasa la hora

Una toma que sigue pendiente cuando se acaba su ventana de
gracia (30 minutos después de la hora programada) queda como
**perdida**. Sigue en tu historial y cuenta en tus
estadísticas. No se puede "recuperar" una toma perdida:
lo que pasó, pasó, y queda registrado así.

## 6. Calendario

En **Calendario** ves tus tomas en un mes o en una semana:

- **Mes:** cada día con tomas muestra un punto de color según
  el estado de sus tomas. Pulsa un día para ver el detalle.
- **Semana:** los 7 días con sus tomas agrupadas por día.

Los días futuros más allá de 72 horas **no muestran tomas
todavía**: las tomas se generan solo para las próximas 72
horas, y el resto aparecerá cuando llegue su momento. No es
un error: es así por diseño.

## 7. Historial y estadísticas

### Historial

En **Historial** están todas tus tomas del periodo que elijas,
ordenadas de la más reciente a la más antigua, con filtros por
fecha, medicamento, tratamiento y estado, y con paginación
("Cargar más"). El historial muestra los 8 estados posibles:

| Estado | Qué significa |
|---|---|
| Pendiente | Todavía no llegó su hora (o llegó y aún estás dentro de la gracia de 30 minutos). |
| Enviando | El aviso se está enviando por Telegram en este momento. |
| Enviada | El aviso llegó a Telegram y está esperando tu respuesta. |
| Tomada | Confirmaste la toma (en la web o en Telegram). Si no tiene hora registrada, es una toma confirmada sin registro de la hora: cuenta como tardía. |
| Pospuesta | La pospusiste: se creó una toma nueva a otra hora. Esta fila es la original. |
| Perdida | Se acabó su ventana de gracia sin que la confirmaras. |
| Cancelada | Se canceló porque se pausó, completó o canceló el tratamiento, se desactivó el medicamento o se eliminó el vínculo con el cuidador. El motivo aparece en la fila; si el motivo es desconocido, lo dice. |
| Fallida | El aviso no se pudo enviar por Telegram tras varios intentos. La toma sigue visible para que actúes tú. |

Una toma pospuesta muestra "Hija de una posposición" cuando
nació de posponer otra.

### Estadísticas

En **Estadísticas** ves tu porcentaje de cumplimiento del
periodo elegido, agrupado por día, por semana, por mes o por
medicamento:

- **A tiempo:** tomas confirmadas dentro de los 30 minutos
  de gracia.
- **Tardías:** tomas confirmadas después de la gracia, o
  confirmadas sin hora registrada.
- **Perdidas:** tomas que se vencieron sin confirmarse.
- **Canceladas:** tomas canceladas (no cuentan en tu
  porcentaje, salvo las de motivo desconocido).

El porcentaje es el número de tomas a tiempo dividido por las
tomas que debías tomar (a tiempo + tardías + perdidas +
canceladas de motivo desconocido). Las canceladas con motivo
conocido (tratamiento cancelado, pausado, completado,
medicamento desactivado o vínculo eliminado) **no** te bajan
el porcentaje: no fue un olvido tuyo. Si en un periodo no
había nada que tomar, el porcentaje aparece vacío ("—"), no
como cero.

## 8. Perfil y zona horaria

En **Perfil** ves tus datos y puedes cambiar tu **zona
horaria** (por ejemplo, si te mudas a otro país). Al
cambiarla:

- Las tomas ya confirmadas, perdidas o enviadas **no cambian**:
  son historia.
- Solo se recalculan las tomas **pendientes futuras**, con la
  misma hora de pared en tu nueva zona (las 08:00 siguen
  siendo las 08:00 donde vivas ahora).

## 9. Cuidadores

Un cuidador es una persona de tu confianza (un familiar, por
ejemplo) que puede ver parte de tu información y ayudarte a
gestionarla, siempre con los permisos que **tú** le concedas.
Tú puedes tener varios cuidadores, y un cuidador puede cuidar
de varias personas.

### Invitar a un cuidador

1. Ve a **Cuidadores** y pulsa para invitar.
2. La aplicación genera un **código de invitación** de 10
   caracteres. Ese código se muestra **una sola vez**: cópialo
   y entrégaselo a tu cuidador por un canal seguro (en
   persona o por mensaje privado).
3. El código caduca en **15 minutos**. Si caduca, genera otro.

### Aceptar como cuidador

1. El cuidador crea su propia cuenta en DosisAlerta y entra
   en **Cuidadores**, en la sección "Soy cuidador de".
2. Escribe el código de invitación y lo envía.
3. **Tú** (el paciente) debes aceptar la invitación en tu
   sección "Mis cuidadores" y elegir qué permisos le das.
   Hasta que no aceptes, el cuidador no ve nada de ti.

### Los 8 permisos (todos en NO por defecto)

| Permiso | Qué permite |
|---|---|
| Ver medicamentos | Ver tu lista de medicamentos. |
| Ver tratamientos | Ver tus tratamientos. |
| Ver horarios | Ver los horarios de tus tratamientos. |
| Ver próximas tomas | Ver qué debes tomar próximamente. |
| Ver historial | Ver tu historial y tus estadísticas. |
| Recibir avisos | Recibir avisos por Telegram cuando no confirmes una toma a tiempo. |
| Gestionar medicamentos | Crear y desactivar medicamentos (nunca cambiar dosis, concentraciones ni unidades). |
| Gestionar horarios | Cambiar las horas de horarios que ya existen (nunca crear horarios ni cambiar frecuencias o días). |

Reglas importantes:

- Para gestionar algo hay que poder verlo: si le das
  "gestionar medicamentos", automáticamente también podrá
  verlos.
- **Ningún cuidador puede confirmar tomas por ti.** No existe
  ese permiso: solo tú confirmas tus tomas.
- Un cuidador nunca puede cambiar tus dosis, tus indicaciones
  médicas ni suspender tus tratamientos.

### Revocar a un cuidador

En **Cuidadores**, pulsa **Revocar** junto al cuidador. La
revocación es **inmediata**: desde ese momento deja de ver tus
datos y de recibir tus avisos. Si quieres volver a invitarle,
se crea un vínculo nuevo; el anterior queda revocado con su
historia intacta. Un cuidador también puede darse de baja él
mismo.

### Ver quién hizo qué con tus datos

En **Cuidadores**, en la sección de auditoría, ves quién
consultó o gestionó tus datos, cuándo y con qué resultado
(permitido o denegado). Todo acceso de un cuidador queda
registrado, también los denegados.

## 10. Telegram

### Vincular tu cuenta

1. Busca el bot en Telegram (el nombre está en
   `docs/bot/CONFIGURACION_TELEGRAM.md`) y pulsa **Iniciar**.
2. Necesitas un **código de vinculación** de 10 caracteres.
   > **Pendiente:** la web todavía no tiene un botón para
   > generar ese código. De momento, el código se genera
   > desde la documentación de la API
   > (`http://localhost:8000/docs`, `POST /telegram/link`)
   > con tu sesión iniciada. Pídelo a quien gestione tu
   > cuenta si no puedes generarlo tú.
3. En el chat con el bot, escribe `/vincular CÓDIGO`
   (sustituyendo `CÓDIGO` por tu código). El código caduca
   en 15 minutos y solo sirve una vez.
4. El bot te confirmará que tu cuenta quedó vinculada.

### Comandos del bot

| Comando | Qué hace |
|---|---|
| `/start` | Saludo y menú principal. |
| `/help` | Ayuda con los comandos. |
| `/vincular CÓDIGO` | Vincula tu cuenta de Telegram con tu cuenta de DosisAlerta. |
| `/vincular_cuidador CÓDIGO` | Acepta una invitación de cuidador desde Telegram (el paciente aún debe aceptar tu invitación en la web). |
| `/medicamentos` | Ver tus medicamentos y crear, editar o desactivar uno. |
| `/proximas` | Ver tus próximas tomas, con botones para confirmar o posponer. |
| `/historial` | Ver tus tomas recientes. |

El bot funciona con **botones**: casi todo se hace pulsando
botones, sin escribir comandos. Si escribes algo que el bot
no entiende, te muestra el menú principal.

### Avisos en Telegram

Cuando llega la hora de una toma y los avisos están activados,
el bot te envía un mensaje con dos botones:

- **✅ YA LO TOMÉ:** confirma la toma (igual que pulsar
  "Tomada" en la web).
- **⏰ RECORDARME DESPUÉS:** te muestra 15, 30 o 60 minutos
  para posponerla.

Si no confirmas a tiempo, tu cuidador (si tiene el permiso de
recibir avisos) puede recibir un aviso, pero **sin botones**:
tu cuidador no puede confirmar tus tomas.

### Desvincular

Para desvincular Telegram, usa la API (`POST /telegram/unlink`)
con tu sesión iniciada. Al desvincular, el bot deja de enviarte
avisos y deja de obedecer tus mensajes hasta que vuelvas a
vincular. > **Pendiente:** la web todavía no tiene un botón
para desvincular; se hace desde la API.

### Qué no hace el bot

- No revela tus datos a nadie que no esté vinculado: si un
  chat no vinculado escribe al bot, no recibe nada de tus
  datos.
- No crea tratamientos: eso solo se hace desde la web.
- No cambia dosis ni indicaciones médicas.

## 11. Qué hacer si algo falla

| Problema | Qué hacer |
|---|---|
| La web no carga | Comprueba que el backend y el frontend estén en marcha (ver la guía de instalación). Si ves un error de conexión, avisa al responsable del proyecto. |
| No puedo entrar | Revisa que el correo y la contraseña sean los correctos. Si olvidaste la contraseña, todavía no hay recuperación automática: avisa al responsable del proyecto. |
| No veo mis tomas | Las tomas solo se generan para las próximas 72 horas. Si tu tratamiento empieza más adelante, aparecerán cuando llegue el momento. Comprueba también que el tratamiento esté activo y no pausado. |
| No me llega el aviso por Telegram | Primero comprueba que tu cuenta esté vinculada (`/start` te dirá si no lo está). Si los avisos no están activados (todavía no hay token real del bot), ningún aviso llegará: es una limitación conocida, no un fallo de tu cuenta. |
| El bot no me responde | Si tu chat no está vinculado, el bot no te dará datos: vincula primero con `/vincular CÓDIGO`. Si estás vinculado y no responde, avisa al responsable del proyecto. |
| Veo un medicamento o tratamiento que no es mío | No debería pasar nunca. No toques nada y avisa de inmediato al responsable del proyecto: es un problema de seguridad. |
| La hora de mis tomas está mal | Revisa tu zona horaria en **Perfil**. Si cambiaste de ciudad o de país, actualízala: solo se recalculan las tomas pendientes futuras. |

Si un error no está en esta tabla, anota qué estabas haciendo,
qué esperabas y qué viste en pantalla, y compártelo con el
responsable del proyecto antes de probar soluciones por tu cuenta.
