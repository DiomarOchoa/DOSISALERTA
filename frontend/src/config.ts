// Configuracion centralizada de la API (Fase 8, Entrega 0).
// La URL base se lee de VITE_API_URL (frontend/.env, copiado de
// .env.example). Si no hay .env, se usa el valor de desarrollo local.
// En la Entrega 1 el cliente HTTP (services/api.ts) usara esta
// misma constante; ninguna pantalla debe definir su propia base.
export const API_URL =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";

// El endpoint de salud versionado vive en <API_URL>/health cuando
// API_URL ya termina en /api/v1; si alguien configura otra base,
// se construye /api/v1/health a partir de ella.
export function healthUrl(apiUrl: string): string {
  const base = apiUrl.replace(/\/$/, "");
  if (base.endsWith("/api/v1")) {
    return `${base}/health`;
  }
  return `${base}/api/v1/health`;
}
