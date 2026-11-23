// Fila del historial de tomas (Fase 8, Entrega 5).
// - Muestra medicamento + dosis, tratamiento como enlace, fecha
//   programada en la zona del usuario, estado, confirmacion y
//   motivo de cancelacion cuando existen.
// - dose_amount es cadena ("500.000"): se muestra tal cual, sin
//   convertir a numero ni operar con ella.
// - TOMADA sin taken_at -> "Tomada (sin hora registrada)" (D-9).
// - Hija de posposicion: parent_reminder_id fijado. El contador
//   solo se muestra cuando postponed_count > 0: las filas
//   sembradas pueden tener padre con contador 0 (Etapa 0).

import { Link } from "react-router-dom";
import type { CancelReason, HistoryItem } from "../services/history";
import { formatInZone } from "../utils/user";
import StatusBadge from "./StatusBadge";

const CANCEL_REASON_LABEL: Record<CancelReason, string> = {
  TREATMENT_CANCELLED: "Tratamiento cancelado",
  TREATMENT_PAUSED: "Tratamiento pausado",
  TREATMENT_COMPLETED: "Tratamiento completado",
  MEDICATION_DEACTIVATED: "Medicamento desactivado",
  LINK_REMOVED: "Medicamento retirado del tratamiento",
};

export default function HistoryRow({
  item,
  timezone,
}: {
  item: HistoryItem;
  timezone: string;
}) {
  return (
    <li className="upcoming-item">
      <div>
        <p className="med-name">{item.medication_name}</p>
        <p className="med-meta">
          {item.dose_amount} {item.dose_unit}
          {" · "}
          {formatInZone(item.scheduled_at, timezone)}
        </p>
        <p className="med-meta">
          <Link
            className="upcoming-treatment-link"
            to={`/tratamientos/${item.treatment_id}`}
          >
            {item.treatment_title}
          </Link>
        </p>
        {item.status === "TOMADA" && item.taken_at !== null ? (
          <p className="med-meta">
            Confirmada: {formatInZone(item.taken_at, timezone)}
            {item.source !== null
              ? ` · ${item.source === "WEB" ? "Web" : "Telegram"}`
              : null}
          </p>
        ) : null}
        {item.status === "TOMADA" && item.taken_at === null ? (
          <p className="med-meta">Tomada (sin hora registrada)</p>
        ) : null}
        {item.status === "CANCELADA" ? (
          <p className="med-meta">
            {item.cancel_reason !== null
              ? CANCEL_REASON_LABEL[item.cancel_reason]
              : "Motivo desconocido"}
          </p>
        ) : null}
        {item.parent_reminder_id !== null ? (
          <p className="med-meta">Hija de una posposición</p>
        ) : null}
        {item.postponed_count > 0 ? (
          <p className="med-meta">
            Pospuesta {item.postponed_count}{" "}
            {item.postponed_count === 1 ? "vez" : "veces"}
          </p>
        ) : null}
        {item.note !== null ? <p className="med-meta">«{item.note}»</p> : null}
      </div>
      <StatusBadge status={item.status} />
    </li>
  );
}
