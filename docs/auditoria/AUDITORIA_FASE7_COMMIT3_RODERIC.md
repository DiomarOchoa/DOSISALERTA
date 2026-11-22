# Auditoría de integración y regresión — Fase 7, hasta el commit 3

- **Autor:** Roderic Gallardo (Roderick_1rg)
- **Fecha:** 2026-11-21
- **Rama:** `feature/roderic-auditoria-fase7`
- **Base auditada:** `feature/fase-7` @ `537e6b6` (commits 1, 2 y 3)
- **Alcance aprobado por:** Diomar Ochoa, 2026-11-21

## Alcance

Auditoría técnica independiente de integración y regresión de lo
implementado en los commits 1, 2 y 3 de la Fase 7:

- Commit 1 (`d39aec4`): migración `cancel_reason` (columna, 2 CHECKs, trigger).
- Commit 2 (`7a061eb`): parámetro `reason` obligatorio en las tres
  funciones `cancel_pending_for_*` y su propagación.
- Commit 3 (`537e6b6`): estadísticas RF14 (sin agrupaciones) e historial RF13.

No se audita el commit 4 (agrupaciones) ni se modifican los commits 1, 2
y 3. No se modificó código de producción, pruebas existentes ni el plan
técnico. No se hizo merge, cherry-pick ni push.

## Método

Los cambios de estado (pausar, cancelar, completar, desactivar un
medicamento, retirar el vínculo de un tratamiento) se ejecutan por los
endpoints REALES de la API, y la verificación se hace por los endpoints
REALES de historial (`GET /api/v1/reminders/history`) y cumplimiento
(`GET /api/v1/stats/compliance`). La siembra de recordatorios es solo
preparación determinista; el objeto auditado son los flujos reales y
sus efectos en el historial y el cumplimiento.

Diferencia con las 122 pruebas formales del plan (commit 5 de Diomar):
esas pruebas siembran filas con estados y motivos ya fijados y verifican
las respuestas de los endpoints; esta auditoría maneja los flujos reales
y verifica que los endpoints reflejen esas operaciones. Las dos
aproximaciones se complementan.

Operaciones controladas de base de datos (autorizadas por Diomar):

- **A-07:** el paso PERDIDA de la reconciliación se invoca directamente
  (`reminder_repository.mark_perdida`), porque el planificador no corre
  en las pruebas. Es el mismo paso que ejecuta el `Reconciler`.
- **A-09:** llamada directa a `cancel_pending_for_treatment` sin motivo
  (debe dar `ValueError`) y un INSERT directo de CANCELADA sin motivo
  dentro de un SAVEPOINT (debe rechazarlo el trigger, sin ensuciar la
  sesión). Es la única forma de probar el cumplimiento del trigger sin
  desactivarlo.
- **A-12:** siembra de una CANCELADA histórica (`cancel_reason` NULL)
  con el trigger desactivado temporalmente y reactivado de inmediato en
  un `try/finally`, para verificar el tratamiento de `unknown` (D-11,
  Alt 3). Es el procedimiento documentado por Diomar para S-71.

## Resultados

### Pruebas de auditoría (13/13 pasadas)

| Prueba | Flujo real auditado | Resultado |
|---|---|---|
| A-01 | Cancelar tratamiento por API | CANCELADA / `TREATMENT_CANCELLED`; denominador 0 → porcentaje null |
| A-02 | Pausar y reanudar por API | Pausa → `TREATMENT_PAUSED`; la reanudación no revive las canceladas y regenera PENDIENTE |
| A-03 | Completar tratamiento por API | CANCELADA / `TREATMENT_COMPLETED` |
| A-04 | Desactivar medicamento por API (I-3) | CANCELADA / `MEDICATION_DEACTIVATED` |
| A-05 | Retirar el vínculo por API | CANCELADA / `LINK_REMOVED`; el historial sigue mostrando las filas (desactivación lógica) |
| A-06 | Confirmar 7 dosis por API y cancelar | 7 TOMADA + 2 PERDIDA + 1 CANCELADA = **77,8 %** (ejemplo de aceptación de D-1) |
| A-07 | PENDIENTE vencida + cancelar | La vencida NO se cancela; la reconciliación la marca PERDIDA y cuenta como perdida (0,0 %) |
| A-08 | ENVIADA + cancelar | La ENVIADA sobrevive, se confirma por API y cuenta como TOMADA (100,0 %) |
| A-09 | Motivo obligatorio y trigger | `ValueError`/`TypeError` sin motivo o con motivo inválido; el trigger rechaza el INSERT sin motivo; con motivo válido se acepta |
| A-10 | Historial | Paginación D-6 (limit/offset/total, offset mayor que total), filtros, orden y 422 |
| A-11 | Cumplimiento | Periodo por defecto D-4 (últimos 30 días, zona del paciente) y 422 |
| A-12 | CANCELADA histórica (unknown) | 1 TOMADA + 1 NULL → **50,0 %** (Alt 3); `unknown = 1` en el desglose |
| A-13 | Cuidador | Con `perm_view_history`: 200 + auditoría `VIEW_HISTORY` OK; sin el permiso: 403 |

Ejecución del archivo de auditoría: **13 passed en 7,39 s**.

### Suite completa (sin regresión)

```
1 failed, 357 passed, 17 warnings in 134,88 s
```

- 357 pasadas = 344 anteriores + 13 nuevas de esta auditoría.
- El único fallo es el conocido y preexistente
  `test_bot_structure.py::test_config_ignora_un_env_ajeno_en_el_directorio_de_trabajo`,
  ajeno a la Fase 7. No hay regresiones.

## Hallazgos

**Ningún defecto de producción.** Las 13 pruebas pasaron contra el
código de `537e6b6` y confirman que los commits 1, 2 y 3 se comportan
según el plan aprobado (D-1 a D-11). No se corrigió código de
producción, conforme a lo autorizado.

## Correcciones a las propias pruebas (no son defectos de producción)

La primera ejecución dio 10 pasadas y 3 fallos. Los 3 fallos eran
errores de las pruebas de auditoría, no de la producción; se
corrigieron y la segunda ejecución dio 13/13:

1. **A-06 y A-11 — índice único `uq_reminders_schedule_time`.** Se
   sembraron varias filas activas con el mismo `(horario, hora)`.
   El índice parcial lo prohíbe (es el comportamiento correcto de
   I-10). Se corrigió sembrando horas distintas dentro de la gracia.
2. **A-13 — `scheduled` del cumplimiento.** La prueba esperaba
   `scheduled == 2` para un paciente con 1 PENDIENTE y 1 TOMADA, pero
   la PENDIENTE no cuenta en `scheduled` (solo las cuatro categorías
   con desenlace). El valor correcto es 1. La aserción estaba mal;
   la producción estaba bien.

## Limitaciones

- La siembra de recordatorios es preparación determinista; los flujos
  auditados son los cambios de estado y la verificación por los
  endpoints. La generación automática de recordatorios por horario
  (top-up de 72 h) no se audita aquí más allá de la regeneración tras
  la reanudación (A-02).
- El paso PERDIDA de la reconciliación (A-07) se invoca directamente
  porque el planificador no corre en las pruebas; no se audita el
  ciclo completo del planificador.
- La fila histórica `unknown` (A-12) solo existe por siembra con el
  trigger desactivado temporalmente; no hay un flujo real que la
  produzca (solo puede venir de datos anteriores a la migración).
- No se auditan las agrupaciones (`group_by`): son el commit 4, fuera
  de este alcance.

## Notas de preparación del worktree

El worktree de Roderic (`DOSISALERTA-RODERIC`) se crea desde Git y no
trae los archivos sin seguimiento de la copia principal. Para poder
ejecutar las pruebas se copiaron (sin modificarlos y sin commitearlos)
dos elementos de la misma PC y del mismo proyecto:

- El `.env` del proyecto (a la raíz del worktree), porque
  `load_dotenv()` lo busca desde el directorio de trabajo y sin él las
  pruebas usarían los valores por defecto (puerto 5432, sin rol
  `dosisalerta`).
- El esqueleto P2 del bot (`backend/app/bot/config.py`, `main.py`,
  `handlers/`, `keyboards/`, `services/` y
  `backend/app/tests/test_bot_structure.py`), porque el backend no es
  importable sin `app/bot/config.py` (la cadena de importación llega
  desde `stats_repository` hasta `telegram_sender`).

Estos archivos siguen sin seguimiento en el worktree, igual que en la
copia principal, y no forman parte de los commits de esta auditoría.

## Archivos y commits

Archivos creados por esta auditoría (únicos modificados):

- `backend/app/tests/test_fase7_audit_roderic.py` (13 pruebas, A-01–A-13)
- `docs/auditoria/AUDITORIA_FASE7_COMMIT3_RODERIC.md` (este informe)

Commits (autor y committer: Roderick_1rg):

1. `test(fase-7): auditoría de integración y regresión hasta commit 3 (A-01–A-13)`
2. `docs(fase-7): informe de auditoría de integración y regresión (commit 3)`
