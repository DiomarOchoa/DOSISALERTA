// Cliente de la API de autenticacion (Fase 3) para el frontend.
// Adaptado en la Entrega 1 a partir del trabajo de Jaider
// (conciliado 6/6 por hashes el 20 nov 2026): las llamadas HTTP
// pasan por el cliente centralizado `services/api.ts`, que anade
// el Bearer, renueva el token ante un 401 y reintenta una vez.
//
// Endpoints (base: VITE_API_URL, ej. http://localhost:8000/api/v1):
//   POST /auth/register -> 201 { user, access_token, refresh_token, token_type }
//   POST /auth/login    -> 200 { access_token, refresh_token, token_type }
//   POST /auth/refresh  -> 200 { access_token, refresh_token, token_type }
//   POST /auth/logout   -> 200 { detail: "Sesión cerrada" }
//   GET  /auth/me       -> 200 UserResponse (requiere Authorization: Bearer <token>)
//   PATCH /auth/me      -> 200 UserResponse (RF03, Etapa 5: cambia la
//                          zona horaria; un cambio regenera solo los
//                          recordatorios PENDIENTE futuros, RNF04)
// Los tokens se guardan en localStorage (decision de la Fase 3 para
// la web; nunca se guardan en el repo). El access token dura 60 min;
// el refresh token, 7 dias, y se rota en cada renovacion.
//
// Correccion de la Entrega 1: `UserResponse` ya no incluye
// `updated_at`, porque el esquema real del backend
// (`schemas/auth.py`) no lo devuelve.

import {
  ApiError,
  clearTokens,
  getAccessToken,
  getRefreshToken,
  request,
  saveTokens,
  type TokenPair,
} from "./api";

export { ApiError, clearTokens, getAccessToken, getRefreshToken, saveTokens };
export type { TokenPair };

export interface UserResponse {
  id: number;
  name: string;
  email: string;
  timezone: string;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface UserRegisterResponse {
  user: UserResponse;
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface RegisterInput {
  name: string;
  email: string;
  password: string;
  timezone: string;
}

export async function register(
  input: RegisterInput,
): Promise<UserRegisterResponse> {
  return request<UserRegisterResponse>("/auth/register", {
    method: "POST",
    body: input,
  });
}

export async function login(
  email: string,
  password: string,
): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

export async function refreshTokens(
  refreshToken: string,
): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });
}

export async function logout(refreshToken: string): Promise<void> {
  await request<{ detail: string }>("/auth/logout", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });
}

export async function fetchMe(): Promise<UserResponse> {
  return request<UserResponse>("/auth/me", { auth: true });
}

// RF03 (Etapa 5): cambia la zona horaria del usuario autenticado.
// Un cambio de zona regenera unicamente los recordatorios PENDIENTE
// futuros (RNF04). Devuelve el perfil actualizado.
export async function updateProfile(input: {
  timezone: string;
}): Promise<UserResponse> {
  return request<UserResponse>("/auth/me", {
    method: "PATCH",
    body: input,
    auth: true,
  });
}

// Restaura la sesion guardada: usa el access token; si esta expirado,
// el cliente centralizado lo renueva una vez con el refresh token.
// Si la renovacion tambien falla, limpia los tokens y devuelve null.
// Sin red (ApiError 0) se propaga el error, para que la pantalla
// pueda distinguir "sin sesion" de "backend no disponible".
export async function restoreSession(): Promise<UserResponse | null> {
  const access = getAccessToken();
  const refresh = getRefreshToken();
  if (!access || !refresh) {
    return null;
  }
  try {
    return await fetchMe();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      clearTokens();
      return null;
    }
    throw error;
  }
}

// La regla del backend: la contrasena mide como maximo 72 bytes UTF-8
// (no 72 caracteres: un caracter acentuado ocupa mas de un byte).
export function passwordTooLong(password: string): boolean {
  return new TextEncoder().encode(password).length > 72;
}
