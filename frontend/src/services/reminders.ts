// Servicio de tomas: confirmar y posponer (Etapa 5).
// Todas las llamadas pasan por el cliente centralizado `request()`
// (services/api.ts): Bearer, 401 -> refresh una vez -> reintento,
// errores como ApiError. Ninguna funcion define su propia base ni
// sus propios headers.
//
// Contrato real del backend (Fase 5, Etapa 4; RF11/RF12):
// - POST /reminders/{id}/confirm (200, sin cuerpo): confirma la
//   toma como WEB. Solo el paciente (un cuidador recibe 403).
//   Idempotente: confirmar dos veces devuelve la misma toma.
//   409 si la toma ya esta POSPUESTA, PERDIDA o CANCELADA.
// - POST /reminders/{id}/postpone (200, cuerpo {delay_minutes}):
//   retrasa la toma 15, 30 o 60 minutos. El original queda
//   POSPUESTA y se crea un hijo PENDIENTE. 422 con otro retraso;
//   409 si la toma ya esta TOMADA, POSPUESTA, PERDIDA o
//   CANCELADA, si ya se pospuso dos veces, si choca con otra toma
//   o si se alcanza el maximo de 3 posposiciones por cadena.
// - `patient_id` no se usa: confirmar y posponer son solo del
//   paciente (el backend lo decide y audita los 403).
// - Las respuestas no traen el nombre del medicamento: la web
//   recarga la lista de proximas tomas tras cada accion.

import { request } from "./api";

export type PostponeDelay = 15 | 30 | 60;

export interface IntakeResponse {
  id: number;
  reminder_id: number;
  user_id: number;
  taken_at: string;
  source: string;
  note: string | null;
  created_at: string;
  reminder_status: string;
}

export interface ReminderResponse {
  id: number;
  schedule_id: number;
  treatment_medication_id: number;
  user_id: number;
  scheduled_at: string;
  status: string;
  parent_reminder_id: number | null;
  postponed_count: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface PostponeResponse {
  original: ReminderResponse;
  child: ReminderResponse;
}

export async function confirmReminder(
  reminderId: number,
): Promise<IntakeResponse> {
  return request<IntakeResponse>(`/reminders/${reminderId}/confirm`, {
    method: "POST",
    auth: true,
  });
}

export async function postponeReminder(
  reminderId: number,
  delayMinutes: PostponeDelay,
): Promise<PostponeResponse> {
  return request<PostponeResponse>(`/reminders/${reminderId}/postpone`, {
    method: "POST",
    body: { delay_minutes: delayMinutes },
    auth: true,
  });
}
