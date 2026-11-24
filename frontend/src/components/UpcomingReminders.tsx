// Lista de proximas tomas de un tratamiento (Fase 8, Entrega 3).
// - Lee solo `upcoming_reminders` del backend: PENDIENTE + ENVIADA,
//   ventana [ahora, ahora+72h), maximo 100 por tratamiento.
// - Nunca calcula tomas: si la lista esta vacia, lo dice con
//   honestidad (la ventana de 72 horas ya termino o el tratamiento
//   todavia no empezo; el motor de la Fase 5 la regenera en cada
//   reanudacion).
// - Las fechas UTC se muestran en la zona horaria del usuario
//   (prop `timezone`, de /me).
// - Si la seccion no viene en la respuesta (D-1: sin permiso de
//   ver proximas tomas), se indica en lugar de fingir un vacio.
// - Entrega 4: con `showTreatment`, cada fila muestra el nombre
//   del tratamiento como enlace a su detalle (la pagina agregada
//   de proximas tomas). Sin esa prop, el comportamiento es el de
//   siempre (detalle de un tratamiento).
// - Etapa 5: con `onConfirm` / `onPostpone`, cada fila ofrece
//   confirmar la toma («Tomada») y posponerla 15, 30 o 60 minutos.
//   Sin esas props no se muestran acciones (detalle de un
//   tratamiento). No hay boton «NO LO HE TOMADO»: eliminado
//   definitivamente por decision del proyecto (2026-11-11).

import { useState } from "react";
import { Link } from "react-router-dom";
import type { Reminder } from "../services/treatments";
import type { PostponeDelay } from "../services/reminders";
import DoseClock from "./DoseClock";
import {
  DAY_PERIOD_LABEL,
  dayPeriod,
  formatDayInZone,
  formatInZone,
} from "../utils/user";

export function formatReminderTime(
  reminder: Reminder,
  timezone: string,
): string {
  return formatInZone(reminder.scheduled_at, timezone);
}

const DELAYS: PostponeDelay[] = [15, 30, 60];

export default function UpcomingReminders({
  reminders,
  timezone,
  showTreatment = false,
  onConfirm,
  onPostpone,
  busyReminderId = null,
}: {
  reminders?: Reminder[];
  timezone: string;
  showTreatment?: boolean;
  onConfirm?: (reminder: Reminder) => void;
  onPostpone?: (reminder: Reminder, delay: PostponeDelay) => void;
  busyReminderId?: number | null;
}) {
  const [postponeId, setPostponeId] = useState<number | null>(null);
  const actionsEnabled = onConfirm !== undefined || onPostpone !== undefined;

  if (reminders === undefined) {
    return (
      <p className="hint">
        Las próximas tomas no están disponibles para este tratamiento.
      </p>
    );
  }

  if (reminders.length === 0) {
    return (
      <p className="hint">
        Sin próximas tomas. Los recordatorios cubren 72 horas desde la
        creación o la última reanudación del tratamiento; pasada esa
        ventana, la lista queda vacía hasta que se genere de nuevo.
      </p>
    );
  }

  const sorted = [...reminders].sort((a, b) =>
    a.scheduled_at < b.scheduled_at
      ? -1
      : a.scheduled_at > b.scheduled_at
        ? 1
        : 0,
  );

  return (
    <ul className="upcoming-list">
      {sorted.map((reminder) => {
        const busy = busyReminderId === reminder.id;
        const pickingDelay = postponeId === reminder.id;
        const period = dayPeriod(reminder.scheduled_at, timezone);
        return (
          <li
            key={reminder.id}
            className={`upcoming-item period-${period}`}
          >
            <div className="dose-time">
              <DoseClock
                className="dose-clock"
                value={reminder.scheduled_at}
                timezone={timezone}
              />
              <span className="dose-period">{DAY_PERIOD_LABEL[period]}</span>
            </div>
            <div className="upcoming-info">
              <p className="med-name">{reminder.medication.name}</p>
              <p className="med-meta">
                {reminder.dose_amount} {reminder.dose_unit}
                {" · "}
                {formatDayInZone(reminder.scheduled_at, timezone, "short")}
              </p>
              {showTreatment ? (
                <p className="med-meta">
                  <Link
                    className="upcoming-treatment-link"
                    to={`/tratamientos/${reminder.treatment.id}`}
                  >
                    {reminder.treatment.title}
                  </Link>
                </p>
              ) : null}
            </div>
            <div className="upcoming-side">
              <span className="badge badge-pending">{reminder.status}</span>
              {actionsEnabled ? (
                <div className="upcoming-actions">
                  {onConfirm ? (
                    <button
                      type="button"
                      className="btn-primary btn-small"
                      disabled={busy}
                      onClick={() => onConfirm(reminder)}
                    >
                      Tomada
                    </button>
                  ) : null}
                  {onPostpone && !pickingDelay ? (
                    <button
                      type="button"
                      className="btn-ghost btn-small"
                      disabled={busy}
                      onClick={() => setPostponeId(reminder.id)}
                    >
                      Posponer
                    </button>
                  ) : null}
                  {onPostpone && pickingDelay ? (
                    <span className="delay-row" role="group" aria-label="Posponer por">
                      {DELAYS.map((delay) => (
                        <button
                          key={delay}
                          type="button"
                          className="btn-ghost btn-small"
                          disabled={busy}
                          onClick={() => {
                            setPostponeId(null);
                            onPostpone(reminder, delay);
                          }}
                        >
                          {delay} min
                        </button>
                      ))}
                      <button
                        type="button"
                        className="btn-ghost btn-small"
                        disabled={busy}
                        onClick={() => setPostponeId(null)}
                      >
                        Cancelar
                      </button>
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
