// Servicio de estadisticas de cumplimiento (Fase 8, Entrega 5).
// Todas las llamadas pasan por el cliente centralizado `request()`
// (services/api.ts): Bearer, 401 -> refresh una vez -> reintento,
// errores como ApiError. Ninguna funcion define su propia base ni
// sus propios headers.
//
// Contrato real del backend (Fase 7, RF14; verificado en vivo en la
// Etapa 0, INFORME_ETAPA0_VERIFICACION_CONTRATOS.md):
// - GET /stats/compliance (?from, ?to, ?medication_id, ?treatment_id,
//   ?patient_id, ?group_by).
// - from/to son FECHAS (YYYY-MM-DD) en la zona del paciente; sin
//   from ni to, ultimos 30 dias [hoy-29, hoy+1). from >= to -> 422.
// - group_by: day, week, month, medication. Sin group_by, groups es
//   null. Sin paginacion.
// - scheduled = taken_on_time + taken_late + lost + cancelled;
//   denominador = scheduled - cancelled + unknown;
//   compliance_percentage = round(taken_on_time / denominador * 100, 1)
//   o null si el denominador es 0. El resumen nunca es el promedio
//   de los grupos: se usa summary tal cual, sin recalcular.
// - Gracia inclusiva de 30 min (D-8); TOMADA sin toma = tardia (D-9).
// - cancelled_by_reason tiene siempre las 6 claves; su suma es
//   cancelled. Los 5 motivos conocidos quedan fuera del denominador;
//   unknown (NULL) entra.
// - Los buckets traen solo su identidad: temporales con period_start
//   + period_label (sin medication_id/name) y por medicamento con
//   medication_id + medication_name (sin period_start/label). El
//   backend omite los campos que no corresponden (exclude_unset):
//   se comprueba presencia, no null.
// - Las series temporales son completas (periodos vacios con
//   scheduled=0 y porcentaje null). Semanas ISO lunes-domingo;
//   meses de calendario. Los grupos por medicamento solo incluyen
//   medicamentos con filas, ordenados por nombre; medication_id es
//   la clave unica (dos medicamentos pueden compartir nombre).
// - patient_id es solo API (cuidador con perm_view_history): la web
//   de la v1 no lo expone.

import { request } from "./api";

export type GroupBy = "day" | "week" | "month" | "medication";

export interface CancelledByReason {
  treatment_cancelled: number;
  treatment_paused: number;
  treatment_completed: number;
  medication_deactivated: number;
  link_removed: number;
  unknown: number;
}

export interface ComplianceSummary {
  from: string;
  to: string;
  scheduled: number;
  taken_on_time: number;
  taken_late: number;
  lost: number;
  cancelled: number;
  cancelled_by_reason: CancelledByReason;
  compliance_percentage: number | null;
}

export interface ComplianceBucket extends ComplianceSummary {
  period_start?: string;
  period_label?: string;
  medication_id?: number;
  medication_name?: string;
}

export interface ComplianceResponse {
  summary: ComplianceSummary;
  groups: ComplianceBucket[] | null;
}

export interface ComplianceFilters {
  from?: string;
  to?: string;
  medication_id?: number;
  treatment_id?: number;
  patient_id?: number;
  group_by?: GroupBy;
}

export async function getCompliance(
  filters: ComplianceFilters = {},
): Promise<ComplianceResponse> {
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
  if (filters.patient_id !== undefined) {
    params.set("patient_id", String(filters.patient_id));
  }
  if (filters.group_by !== undefined) {
    params.set("group_by", filters.group_by);
  }
  const query = params.toString();
  return request<ComplianceResponse>(
    query ? `/stats/compliance?${query}` : "/stats/compliance",
    { auth: true },
  );
}
