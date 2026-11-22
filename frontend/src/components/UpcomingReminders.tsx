// Lista de proximas tomas de un tratamiento (Fase 8, Entrega 3).
// - Lee solo `upcoming_reminders` del backend: PENDIENTE + ENVIADA,
//   ventana [ahora, ahora+72h), maximo 100 por tratamiento.
// - Nunca calcula tomas: si la lista esta vacia, lo dice con
//   honestidad (la ventana de 72 horas ya termino o el tratamiento
//   todavia no empezo).
// - Las fechas UTC se muestran en la zona horaria del usuario
//   (prop `timezone`, de /me).
// - Si la seccion no viene en la respuesta (D-1: sin permiso de
//   ver proximas tomas), se indica en lugar de fingir un vacio.
// - Entrega 4: con `showTreatment`, cada fila muestra el nombre
//   del tratamiento como enlace a su detalle (la pagina agregada
//   de proximas tomas). Sin esa prop, el comportamiento es el de
//   siempre (detalle de un tratamiento).

import { Link } from "react-router-dom";
import type { Reminder } from "../services/treatments";
import { formatInZone } from "../utils/user";

export function formatReminderTime(
  reminder: Reminder,
  timezone: string,
): string {
  return formatInZone(reminder.scheduled_at, timezone);
}

export default function UpcomingReminders({
  reminders,
  timezone,
  showTreatment = false,
}: {
  reminders?: Reminder[];
  timezone: string;
  showTreatment?: boolean;
}) {
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
        ventana, la lista queda vacía hasta que se genere de nuevo
        (motor de recordatorios, Fase 5).
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
      {sorted.map((reminder) => (
        <li key={reminder.id} className="upcoming-item">
          <div>
            <p className="med-name">{reminder.medication.name}</p>
            <p className="med-meta">
              {reminder.dose_amount} {reminder.dose_unit}
              {" · "}
              {formatReminderTime(reminder, timezone)}
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
          <span className="badge badge-pending">{reminder.status}</span>
        </li>
      ))}
    </ul>
  );
}
