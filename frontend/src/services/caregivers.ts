// Servicio de cuidadores (Etapa 5, RF20–RF22).
// Todas las llamadas pasan por el cliente centralizado `request()`
// (services/api.ts): Bearer, 401 -> refresh una vez -> reintento,
// errores como ApiError. Ninguna funcion define su propia base ni
// sus propios headers.
//
// Contrato real del backend (Etapa 5):
// - POST /caregivers/invite (201): crea la invitacion y devuelve
//   el codigo UNA SOLA VEZ (`invite_code`). El codigo caduca en
//   15 minutos y nunca se devuelve en ningun GET.
// - POST /caregivers/accept-code (200, {code}): el cuidador
//   presenta el codigo y vincula su identidad. El vinculo sigue
//   INVITADO hasta que el paciente lo acepta.
// - GET /caregivers (200): mis vinculos, como paciente y como
//   cuidador. Sin `patient_id`: la gestion es del propio usuario.
// - POST /caregivers/{id}/accept (200, {permissions}): el paciente
//   acepta y fija los permisos iniciales; el vinculo pasa a ACTIVO.
// - PATCH /caregivers/{id}/permissions (200, {permissions}): el
//   paciente cambia los permisos de un vinculo ACTIVO.
// - POST /caregivers/{id}/revoke (200): revoca el vinculo (lo puede
//   hacer el paciente o el cuidador). No hay vuelta de REVOCADO.
// - GET /caregivers/audit (200, ?limit&offset): auditoria del
//   paciente: quien hizo que sobre sus datos.
// - Los 8 permisos empiezan en False. Gestionar exige poder ver:
//   el backend rechaza con 422 un conjunto que lo viole.

import { request } from "./api";

export interface CaregiverPermissions {
  perm_view_medications: boolean;
  perm_view_treatments: boolean;
  perm_view_schedules: boolean;
  perm_view_upcoming: boolean;
  perm_view_history: boolean;
  perm_receive_notifications: boolean;
  perm_manage_medications: boolean;
  perm_manage_schedules: boolean;
}

export const EMPTY_PERMISSIONS: CaregiverPermissions = {
  perm_view_medications: false,
  perm_view_treatments: false,
  perm_view_schedules: false,
  perm_view_upcoming: false,
  perm_view_history: false,
  perm_receive_notifications: false,
  perm_manage_medications: false,
  perm_manage_schedules: false,
};

export const PERMISSION_LABELS: {
  key: keyof CaregiverPermissions;
  label: string;
  hint: string;
}[] = [
  {
    key: "perm_view_medications",
    label: "Ver medicamentos",
    hint: "Ver la lista y el detalle de tus medicamentos.",
  },
  {
    key: "perm_view_treatments",
    label: "Ver tratamientos",
    hint: "Ver tus tratamientos y sus estados.",
  },
  {
    key: "perm_view_schedules",
    label: "Ver horarios",
    hint: "Ver los horarios de cada medicamento.",
  },
  {
    key: "perm_view_upcoming",
    label: "Ver próximas tomas",
    hint: "Ver tus próximos recordatorios ordenados.",
  },
  {
    key: "perm_view_history",
    label: "Ver historial",
    hint: "Ver tomas, perdidas, pospuestas y cumplimiento.",
  },
  {
    key: "perm_receive_notifications",
    label: "Recibir avisos",
    hint: "Recibir un aviso si no confirmas una toma en 30 minutos. El aviso es informativo, sin botones.",
  },
  {
    key: "perm_manage_medications",
    label: "Gestionar medicamentos",
    hint: "Crear medicamentos y editar nombre, presentación y notas. Nunca puede cambiar dosis ni concentraciones.",
  },
  {
    key: "perm_manage_schedules",
    label: "Gestionar horarios",
    hint: "Editar solo las horas de horarios existentes. Nunca puede crear horarios ni cambiar la frecuencia.",
  },
];

export interface CaregiverLink {
  id: number;
  patient_user_id: number;
  patient_name: string | null;
  caregiver_user_id: number | null;
  caregiver_name: string | null;
  caregiver_email: string | null;
  status: "INVITADO" | "ACTIVO" | "REVOCADO";
  perm_view_medications: boolean;
  perm_view_treatments: boolean;
  perm_view_schedules: boolean;
  perm_view_upcoming: boolean;
  perm_view_history: boolean;
  perm_receive_notifications: boolean;
  perm_manage_medications: boolean;
  perm_manage_schedules: boolean;
  invited_at: string;
  invite_expires_at: string | null;
  accepted_at: string | null;
  revoked_at: string | null;
}

export interface InviteResponse extends CaregiverLink {
  invite_code: string;
}

export interface CaregiverLinks {
  as_patient: CaregiverLink[];
  as_caregiver: CaregiverLink[];
}

export interface CaregiverAuditEntry {
  id: number;
  caregiver_user_id: number | null;
  caregiver_name: string | null;
  patient_user_id: number;
  action: string;
  target_type: string | null;
  target_id: number | null;
  details: Record<string, unknown> | null;
  result: string;
  created_at: string;
}

export interface CaregiverAuditPage {
  items: CaregiverAuditEntry[];
  total: number;
  limit: number;
  offset: number;
}

export function permissionsOf(link: CaregiverLink): CaregiverPermissions {
  return {
    perm_view_medications: link.perm_view_medications,
    perm_view_treatments: link.perm_view_treatments,
    perm_view_schedules: link.perm_view_schedules,
    perm_view_upcoming: link.perm_view_upcoming,
    perm_view_history: link.perm_view_history,
    perm_receive_notifications: link.perm_receive_notifications,
    perm_manage_medications: link.perm_manage_medications,
    perm_manage_schedules: link.perm_manage_schedules,
  };
}

export async function inviteCaregiver(): Promise<InviteResponse> {
  return request<InviteResponse>("/caregivers/invite", {
    method: "POST",
    auth: true,
  });
}

export async function acceptCaregiverCode(code: string): Promise<CaregiverLink> {
  return request<CaregiverLink>("/caregivers/accept-code", {
    method: "POST",
    body: { code },
    auth: true,
  });
}

export async function listCaregiverLinks(): Promise<CaregiverLinks> {
  return request<CaregiverLinks>("/caregivers", { auth: true });
}

export async function acceptCaregiverLink(
  id: number,
  permissions: CaregiverPermissions,
): Promise<CaregiverLink> {
  return request<CaregiverLink>(`/caregivers/${id}/accept`, {
    method: "POST",
    body: { permissions },
    auth: true,
  });
}

export async function updateCaregiverPermissions(
  id: number,
  permissions: CaregiverPermissions,
): Promise<CaregiverLink> {
  return request<CaregiverLink>(`/caregivers/${id}/permissions`, {
    method: "PATCH",
    body: { permissions },
    auth: true,
  });
}

export async function revokeCaregiverLink(id: number): Promise<CaregiverLink> {
  return request<CaregiverLink>(`/caregivers/${id}/revoke`, {
    method: "POST",
    auth: true,
  });
}

export async function getCaregiverAudit(
  limit = 50,
  offset = 0,
): Promise<CaregiverAuditPage> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return request<CaregiverAuditPage>(`/caregivers/audit?${params.toString()}`, {
    auth: true,
  });
}
