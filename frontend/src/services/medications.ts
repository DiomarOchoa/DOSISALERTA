// Servicio de medicamentos (Fase 8, Entrega 2).
// Todas las llamadas pasan por el cliente centralizado `request()`
// (services/api.ts): Bearer, 401 -> refresh una vez -> reintento,
// errores como ApiError. Ninguna funcion define su propia base ni
// sus propios headers.
//
// Contrato real del backend (Fase 4, RF04; verificado en vivo):
// - POST /medications (201), GET /medications (?is_active, ?limit),
//   GET /medications/{id}, PATCH /medications/{id}, DELETE (200),
//   POST /medications/{id}/reactivate (200, I-7).
// - MedicationCreate: name 1-150 (no en blanco), presentation <=100,
//   concentration <=50, unit <=30, notes opcional.
// - MedicationUpdate: todos opcionales, al menos uno (si no, 422);
//   un campo en null lo borra. NO incluye is_active.
// - MedicationResponse: id, name, presentation, concentration, unit,
//   notes, is_active, created_at, updated_at.
// - 404 si el recurso no existe; 403 si existe pero es de otro
//   usuario. `patient_id` es solo API: la web no lo expone.

import { request } from "./api";

export interface Medication {
  id: number;
  name: string;
  presentation: string | null;
  concentration: string | null;
  unit: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface MedicationCreateInput {
  name: string;
  presentation?: string | null;
  concentration?: string | null;
  unit?: string | null;
  notes?: string | null;
}

export interface MedicationUpdateInput {
  name?: string | null;
  presentation?: string | null;
  concentration?: string | null;
  unit?: string | null;
  notes?: string | null;
}

// El listado del backend viene ordenado por nombre. Se pide el maximo
// permitido (200) para no recortar la lista en silencio con el
// valor por defecto (100).
export async function listMedications(
  isActive = true,
): Promise<Medication[]> {
  const params = new URLSearchParams({
    is_active: isActive ? "true" : "false",
    limit: "200",
  });
  return request<Medication[]>(`/medications?${params.toString()}`, {
    auth: true,
  });
}

export async function getMedication(id: number): Promise<Medication> {
  return request<Medication>(`/medications/${id}`, { auth: true });
}

export async function createMedication(
  data: MedicationCreateInput,
): Promise<Medication> {
  return request<Medication>("/medications", {
    method: "POST",
    body: data,
    auth: true,
  });
}

export async function updateMedication(
  id: number,
  data: MedicationUpdateInput,
): Promise<Medication> {
  return request<Medication>(`/medications/${id}`, {
    method: "PATCH",
    body: data,
    auth: true,
  });
}

// DELETE del backend = desactivacion logica (is_active=false, 200).
// La reactivacion existe desde I-7 (Fase 7): POST
// /medications/{id}/reactivate (200, idempotente). Reactivar no
// revive los recordatorios CANCELADA al desactivar; los
// tratamientos vuelven a generar tomas en la proxima reanudacion
// del motor.
export async function deactivateMedication(
  id: number,
): Promise<Medication> {
  return request<Medication>(`/medications/${id}`, {
    method: "DELETE",
    auth: true,
  });
}

export async function reactivateMedication(
  id: number,
): Promise<Medication> {
  return request<Medication>(`/medications/${id}/reactivate`, {
    method: "POST",
    auth: true,
  });
}
