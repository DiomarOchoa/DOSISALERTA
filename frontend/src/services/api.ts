// Cliente HTTP centralizado de DosisAlerta (Fase 8, Entrega 1).
// Todas las pantallas y servicios usan `request()`; ninguna define
// su propia base ni sus propios headers de autorizacion.
//
// Reglas:
// - La base es API_URL (config.ts, desde VITE_API_URL).
// - Con `auth: true` se envia `Authorization: Bearer <access>`.
// - Ante un 401, se renueva el access token UNA sola vez con el
//   refresh guardado y se reintenta la solicitud original. Si la
//   renovacion falla, se limpian los tokens y se propaga el 401.
//   La renovacion usa fetch directo (sin pasar por `request`) y
//   una promesa compartida, asi no hay ciclos ni renovaciones
//   duplicadas cuando varias solicitudes fallan a la vez.
// - 403, 409 y 422 se propagan como ApiError con su estado y el
//   mensaje del backend. Sin red, ApiError con estado 0.

import { API_URL } from "../config";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
}

const ACCESS_KEY = "dosisalerta_access_token";
const REFRESH_KEY = "dosisalerta_refresh_token";

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function saveTokens(tokens: TokenPair): void {
  localStorage.setItem(ACCESS_KEY, tokens.access_token);
  localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

// Extrae un mensaje legible de una respuesta de error de FastAPI.
// 401/403/409 traen { detail: "..." }; 422 trae { detail: [{ loc, msg }] }.
async function errorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const data: unknown = await response.json();
    if (typeof data === "object" && data !== null && "detail" in data) {
      const detail: unknown = (data as { detail: unknown }).detail;
      if (typeof detail === "string") {
        return detail;
      }
      if (Array.isArray(detail) && detail.length > 0) {
        const first: unknown = detail[0];
        if (
          typeof first === "object" &&
          first !== null &&
          "msg" in first &&
          typeof (first as { msg: unknown }).msg === "string"
        ) {
          return (first as { msg: string }).msg;
        }
      }
    }
  } catch {
    // La respuesta no es JSON: se usa el mensaje generico.
  }
  return fallback;
}

// Renovacion compartida: si varias solicitudes reciben 401 a la vez,
// todas esperan la misma renovacion en curso en lugar de lanzar una
// cada una (la segunda renovacion con el mismo refresh fallaria,
// porque la primera rotacion ya lo revoco).
let refreshInFlight: Promise<TokenPair> | null = null;

function refreshTokensOnce(): Promise<TokenPair> {
  if (!refreshInFlight) {
    const refresh = getRefreshToken();
    if (!refresh) {
      return Promise.reject(
        new ApiError(401, "No hay sesión guardada."),
      );
    }
    refreshInFlight = (async () => {
      let response: Response;
      try {
        response = await fetch(`${API_URL}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
      } catch {
        throw new ApiError(
          0,
          "No se pudo contactar al backend. Comprueba que esta corriendo en el puerto 8000.",
        );
      }
      if (!response.ok) {
        throw new ApiError(
          response.status,
          await errorMessage(
            response,
            `El servidor respondio HTTP ${response.status}.`,
          ),
        );
      }
      return (await response.json()) as TokenPair;
    })();
    const done = () => {
      refreshInFlight = null;
    };
    refreshInFlight.then(done, done);
  }
  return refreshInFlight;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean;
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, auth = false } = options;
  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (auth) {
    const access = getAccessToken();
    if (access) {
      headers["Authorization"] = `Bearer ${access}`;
    }
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(
      0,
      "No se pudo contactar al backend. Comprueba que esta corriendo en el puerto 8000.",
    );
  }

  if (response.status === 401 && auth) {
    // Un solo reintento: si la renovacion falla, se cierra la sesion
    // local y se propaga el 401 sin volver a intentarlo.
    try {
      const tokens = await refreshTokensOnce();
      saveTokens(tokens);
    } catch {
      clearTokens();
      throw new ApiError(401, "Tu sesión expiró. Inicia sesión de nuevo.");
    }
    const retryHeaders: Record<string, string> = {
      ...headers,
      Authorization: `Bearer ${getAccessToken() ?? ""}`,
    };
    try {
      response = await fetch(`${API_URL}${path}`, {
        method,
        headers: retryHeaders,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw new ApiError(
        0,
        "No se pudo contactar al backend. Comprueba que esta corriendo en el puerto 8000.",
      );
    }
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      await errorMessage(
        response,
        `El servidor respondio HTTP ${response.status}.`,
      ),
    );
  }
  return (await response.json()) as T;
}
