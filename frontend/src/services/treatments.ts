// Servicio de tratamientos (Fase 8, Entrega 3).
// Todas las llamadas pasan por el cliente centralizado `request()`
// (services/api.ts): Bearer, 401 -> refresh una vez -> reintento,
// errores como ApiError. Ninguna funcion define su propia base ni
// sus propios headers.
//
// Contrato real del backend (Fase 4, RF05/RF06/RF08; verificado en
// el diagnostico de la Entrega 3):
// - POST /treatments (201), GET /treatments (?status, ?limit),
//   GET /treatments/{id}, PATCH /treatments/{id},
//   POST /treatments/{id}/pause|resume|cancel|complete (200).
// - POST /treatments/{id}/medications (201),
//   PATCH /treatments/{id}/medications/{link_id} (200),
//   DELETE /treatments/{id}/medications/{link_id} (200, desactivacion
//   logica del vinculo).
// - Estados: ACTIVO, PAUSADO, COMPLETADO, CANCELADO. ACTIVO ->
//   PAUSADO/CANCELADO/COMPLETADO; PAUSADO -> ACTIVO/CANCELADO;
//   CANCELADO y COMPLETADO son terminales (400).
// - TreatmentCreate: title 1-150 (no en blanco), start_date
//   obligatorio, end_date >= start_date, medications >= 1 y cada
//   medicamento con >= 1 horario.
// - TreatmentUpdate: solo title, notes, end_date; al menos un campo.
// - TreatmentMedicationCreate: medication_id, dose_amount > 0
//   (max. 10 digitos, 3 decimales), dose_unit 1-30, instructions
//   opcional, schedules opcional aqui (la web exige >= 1, decision 1).
// - TreatmentMedicationUpdate: solo dose_amount, dose_unit,
//   instructions; al menos un campo.
// - ScheduleCreate: frequency DIARIO | DIAS_SEMANA | INTERVALO_DIAS;
//   DIAS_SEMANA exige days_of_week (0=lunes..6); INTERVALO_DIAS exige
//   interval_days >= 1; times >= 1 hora.
// - NO existe endpoint para editar horarios ni para confirmar o
//   posponer tomas. `dose_amount` llega como numero JSON.
// - `medications` y `upcoming_reminders` son secciones opcionales
//   (D-1): pueden no venir en la respuesta.
// - `patient_id` es solo API: la web no lo expone.

import { request } from "./api";

export type TreatmentStatus =
  | "ACTIVO"
  | "PAUSADO"
  | "COMPLETADO"
  | "CANCELADO";

export type ScheduleFrequency =
  | "DIARIO"
  | "DIAS_SEMANA"
  | "INTERVALO_DIAS";

export interface MedicationSummary {
  id: number;
  name: string;
  presentation: string | null;
  concentration: string | null;
}

export interface Schedule {
  id: number;
  treatment_medication_id: number;
  frequency: ScheduleFrequency;
  days_of_week: number[] | null;
  interval_days: number | null;
  times: string[];
  start_date: string;
  end_date: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface TreatmentMedication {
  id: number;
  medication_id: number;
  medication: MedicationSummary;
  dose_amount: number;
  dose_unit: string;
  instructions: string | null;
  is_active: boolean;
  schedules?: Schedule[];
  created_at: string;
  updated_at: string;
}

export interface Reminder {
  id: number;
  scheduled_at: string;
  status: string;
  medication: MedicationSummary;
  dose_amount: number;
  dose_unit: string;
  treatment: { id: number; title: string };
  schedule_id: number;
}

export interface Treatment {
  id: number;
  title: string;
  notes: string | null;
  start_date: string;
  end_date: string | null;
  status: TreatmentStatus;
  medications?: TreatmentMedication[];
  upcoming_reminders?: Reminder[];
  created_at: string;
  updated_at: string;
}

export interface ScheduleCreateInput {
  frequency: ScheduleFrequency;
  days_of_week?: number[] | null;
  interval_days?: number | null;
  times: string[];
  start_date: string;
  end_date?: string | null;
}

export interface TreatmentMedicationCreateInput {
  medication_id: number;
  dose_amount: number;
  dose_unit: string;
  instructions?: string | null;
  schedules?: ScheduleCreateInput[];
}

export interface TreatmentCreateInput {
  title: string;
  notes?: string | null;
  start_date: string;
  end_date?: string | null;
  medications: TreatmentMedicationCreateInput[];
}

export interface TreatmentUpdateInput {
  title?: string | null;
  notes?: string | null;
  end_date?: string | null;
}

export interface TreatmentMedicationUpdateInput {
  dose_amount?: number;
  dose_unit?: string;
  instructions?: string | null;
}

// El listado del backend viene ordenado por start_date DESC. Se
// pide el maximo permitido (200) para no recortar la lista en
// silencio con el valor por defecto (100). El filtro por estado se
// hace en el cliente sobre esta unica carga: la respuesta ya trae
// las secciones anidadas completas y pedirla por estado no la
// aligera.
export async function listTreatments(): Promise<Treatment[]> {
  const params = new URLSearchParams({ limit: "200" });
  return request<Treatment[]>(`/treatments?${params.toString()}`, {
    auth: true,
  });
}

export async function getTreatment(id: number): Promise<Treatment> {
  return request<Treatment>(`/treatments/${id}`, { auth: true });
}

export async function createTreatment(
  data: TreatmentCreateInput,
): Promise<Treatment> {
  return request<Treatment>("/treatments", {
    method: "POST",
    body: data,
    auth: true,
  });
}

export async function updateTreatment(
  id: number,
  data: TreatmentUpdateInput,
): Promise<Treatment> {
  return request<Treatment>(`/treatments/${id}`, {
    method: "PATCH",
    body: data,
    auth: true,
  });
}

export async function pauseTreatment(id: number): Promise<Treatment> {
  return request<Treatment>(`/treatments/${id}/pause`, {
    method: "POST",
    auth: true,
  });
}

export async function resumeTreatment(id: number): Promise<Treatment> {
  return request<Treatment>(`/treatments/${id}/resume`, {
    method: "POST",
    auth: true,
  });
}

export async function cancelTreatment(id: number): Promise<Treatment> {
  return request<Treatment>(`/treatments/${id}/cancel`, {
    method: "POST",
    auth: true,
  });
}

export async function completeTreatment(id: number): Promise<Treatment> {
  return request<Treatment>(`/treatments/${id}/complete`, {
    method: "POST",
    auth: true,
  });
}

export async function addTreatmentMedication(
  treatmentId: number,
  data: TreatmentMedicationCreateInput,
): Promise<TreatmentMedication> {
  return request<TreatmentMedication>(
    `/treatments/${treatmentId}/medications`,
    { method: "POST", body: data, auth: true },
  );
}

export async function updateTreatmentMedication(
  treatmentId: number,
  linkId: number,
  data: TreatmentMedicationUpdateInput,
): Promise<TreatmentMedication> {
  return request<TreatmentMedication>(
    `/treatments/${treatmentId}/medications/${linkId}`,
    { method: "PATCH", body: data, auth: true },
  );
}

// DELETE del backend = desactivacion logica del vinculo
// (is_active=false, 200) + cancelacion de sus recordatorios
// futuros. El indice parcial permite volver a anadir el mismo
// medicamento despues (es el procedimiento para "editar" un
// horario: quitar y volver a anadir).
export async function removeTreatmentMedication(
  treatmentId: number,
  linkId: number,
): Promise<TreatmentMedication> {
  return request<TreatmentMedication>(
    `/treatments/${treatmentId}/medications/${linkId}`,
    { method: "DELETE", auth: true },
  );
}

// La toma mas proxima entre varios tratamientos: el recordatorio
// con menor `scheduled_at` dentro de `upcoming_reminders`.
// Solo lectura de datos reales; nunca se calcula una toma.
export function findNextReminder(
  treatments: Treatment[],
): Reminder | null {
  let next: Reminder | null = null;
  for (const treatment of treatments) {
    if (treatment.status !== "ACTIVO") {
      continue;
    }
    for (const reminder of treatment.upcoming_reminders ?? []) {
      if (!next || reminder.scheduled_at < next.scheduled_at) {
        next = reminder;
      }
    }
  }
  return next;
}

// Todas las próximas tomas del usuario en una sola lista ordenada
// (Fase 8, Entrega 4): se aplana `upcoming_reminders` de los
// tratamientos ACTIVO y se ordena por `scheduled_at`, con
// desempate por `id` (orden determinista). Solo lectura de datos
// reales; nunca se calcula una toma.
//
// Se filtra a ACTIVO por coherencia con `findNextReminder`: un
// tratamiento PAUSADO, COMPLETADO o CANCELADO no tiene próximas
// tomas que tomar (el backend ya devuelve sus secciones vacías);
// el filtro solo cubre el caso límite de una ENVIADA residual en
// un tratamiento pausado, que no es una dosis pendiente.
export function collectUpcomingReminders(
  treatments: Treatment[],
): Reminder[] {
  const all: Reminder[] = [];
  for (const treatment of treatments) {
    if (treatment.status !== "ACTIVO") {
      continue;
    }
    for (const reminder of treatment.upcoming_reminders ?? []) {
      all.push(reminder);
    }
  }
  all.sort((a, b) =>
    a.scheduled_at < b.scheduled_at
      ? -1
      : a.scheduled_at > b.scheduled_at
        ? 1
        : a.id - b.id,
  );
  return all;
}

// ¿Algún tratamiento ACTIVO no trae su sección `upcoming_reminders`?
// (D-1: sin permiso de ver próximas tomas, la sección queda ausente
// del JSON, ni `null` ni lista vacía.) Distinto de una lista vacía:
// ausente = no disponible, vacía = sin próximas tomas.
export function hasUnavailableUpcoming(
  treatments: Treatment[],
): boolean {
  return treatments.some(
    (treatment) =>
      treatment.status === "ACTIVO" &&
      treatment.upcoming_reminders === undefined,
  );
}
