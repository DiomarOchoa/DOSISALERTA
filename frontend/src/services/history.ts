// Servicio de historial de tomas (Fase 8, Entrega 5).
// Todas las llamadas pasan por el cliente centralizado `request()`
// (services/api.ts): Bearer, 401 -> refresh una vez -> reintento,
// errores como ApiError. Ninguna funcion define su propia base ni
// sus propios headers.
//
// Contrato real del backend (Fase 7, RF13; verificado en vivo en la
// Etapa 0, INFORME_ETAPA0_VERIFICACION_CONTRATOS.md):
// - GET /reminders/history (?from, ?to, ?medication_id, ?treatment_id,
//   ?status, ?limit, ?offset, ?patient_id).
// - from/to son datetimes ISO 8601 y filtran por scheduled_at con
//   [from, to); sin zona se asumen UTC. Sin from/to no hay filtro
//   implicito: se devuelven todas las tomas.
// - from >= to -> 422 {"detail": "from debe ser anterior a to"}.
// - status es un solo valor de los 8; otro valor -> 422.
// - limit por defecto 50 (1-200); offset por defecto 0 (>= 0).
//   offset mayor que total -> 200 con items: [].
// - Orden fijo: scheduled_at DESC, id DESC. Sin ordenacion.
// - Los 8 estados aparecen, incluidas las dosis futuras ya generadas
//   (horizonte 72 h); siempre el estado almacenado (una PENDIENTE
//   pasada de gracia sigue PENDIENTE hasta la reconciliacion).
// - dose_amount llega como CADENA decimal con 3 decimales ("500.000"),
//   distinto de TreatmentMedication, donde llega como numero.
// - Una TOMADA sin toma registrada trae taken_at null y source null
//   (D-9: cuenta como tardia por convencion).
// - patient_id es solo API (cuidador con perm_view_history): la web
//   de la v1 no lo expone.

import { request } from "./api";

export type ReminderStatus =
  | "PENDIENTE"
  | "ENVIANDO"
  | "ENVIADA"
  | "TOMADA"
  | "POSPUESTA"
  | "PERDIDA"
  | "CANCELADA"
  | "FALLIDA";

export type CancelReason =
  | "TREATMENT_CANCELLED"
  | "TREATMENT_PAUSED"
  | "TREATMENT_COMPLETED"
  | "MEDICATION_DEACTIVATED"
  | "LINK_REMOVED";

export type IntakeSource = "WEB" | "TELEGRAM";

export interface HistoryItem {
  id: number;
  scheduled_at: string;
  status: ReminderStatus;
  cancel_reason: CancelReason | null;
  parent_reminder_id: number | null;
  postponed_count: number;
  medication_id: number;
  medication_name: string;
  dose_amount: string;
  dose_unit: string;
  treatment_id: number;
  treatment_title: string;
  taken_at: string | null;
  source: IntakeSource | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface HistoryPage {
  items: HistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface HistoryFilters {
  from?: string;
  to?: string;
  medication_id?: number;
  treatment_id?: number;
  status?: ReminderStatus;
  limit?: number;
  offset?: number;
  patient_id?: number;
}

export async function getHistory(
  filters: HistoryFilters = {},
): Promise<HistoryPage> {
  const params = new URLSearchParams();
  if (filters.from !== undefined) {
    params.set("from", filters.from);
  }
  if (filters.to !== undefined) {
    params.set("to", filters.to);
  }
  if (filters.medication_id !== undefined) {
    params.set("medication_id", String(filters.medication_id));
  }
  if (filters.treatment_id !== undefined) {
    params.set("treatment_id", String(filters.treatment_id));
  }
  if (filters.status !== undefined) {
    params.set("status", filters.status);
  }
  if (filters.limit !== undefined) {
    params.set("limit", String(filters.limit));
  }
  if (filters.offset !== undefined) {
    params.set("offset", String(filters.offset));
  }
  if (filters.patient_id !== undefined) {
    params.set("patient_id", String(filters.patient_id));
  }
  const query = params.toString();
  return request<HistoryPage>(
    query ? `/reminders/history?${query}` : "/reminders/history",
    { auth: true },
  );
}
