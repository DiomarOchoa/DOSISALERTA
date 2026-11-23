// Badge de estado de un recordatorio (Fase 8, Entrega 5).
// - Un solo sitio conoce el color y la etiqueta de cada estado.
// - La etiqueta es la forma legible del estado del backend
//   ("Tomada", "Pendiente"...), no el codigo en mayusculas.

import type { ReminderStatus } from "../services/history";

const STATUS_CLASS: Record<ReminderStatus, string> = {
  TOMADA: "badge-done",
  PENDIENTE: "badge-pending",
  ENVIADA: "badge-progress",
  ENVIANDO: "badge-progress",
  POSPUESTA: "badge-postponed",
  PERDIDA: "badge-lost",
  CANCELADA: "badge-cancelled",
  FALLIDA: "badge-lost",
};

const STATUS_LABEL: Record<ReminderStatus, string> = {
  TOMADA: "Tomada",
  PENDIENTE: "Pendiente",
  ENVIADA: "Enviada",
  ENVIANDO: "Enviando",
  POSPUESTA: "Pospuesta",
  PERDIDA: "Perdida",
  CANCELADA: "Cancelada",
  FALLIDA: "Fallida",
};

export default function StatusBadge({ status }: { status: ReminderStatus }) {
  return (
    <span className={`badge ${STATUS_CLASS[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}
