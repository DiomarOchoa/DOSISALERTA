// Cliente de la API de vinculación de Telegram (Etapa 6, RF15) para el frontend.
// Las llamadas HTTP pasan por el cliente centralizado `services/api.ts`,
// que añade el Bearer, renueva el token ante un 401 y reintenta una vez.
//
// Endpoints (base: VITE_API_URL, ej. http://localhost:8000/api/v1):
//   POST /telegram/link   -> 201 { code, expires_at } (el código se muestra UNA SOLA VEZ)
//   GET  /telegram/status -> 200 { status, telegram_username, linked_at, has_pending_code }
//   POST /telegram/unlink -> 200 { status, telegram_username, linked_at, has_pending_code }
// El código caduca en 15 minutos y generar uno nuevo invalida el anterior;
// si la cuenta ya estaba VINCULADA, generar un código la deja PENDIENTE
// y sin chat hasta que el nuevo código se confirme en el bot.

import { ApiError, request } from "./api";

export { ApiError };

export type TelegramLinkStatus =
  | "SIN_VINCULAR"
  | "PENDIENTE"
  | "VINCULADA"
  | "REVOCADA";

export interface TelegramLinkCode {
  code: string;
  expires_at: string;
}

export interface TelegramLinkStatusResponse {
  status: TelegramLinkStatus;
  telegram_username: string | null;
  linked_at: string | null;
  has_pending_code: boolean;
}

export async function fetchTelegramStatus(): Promise<TelegramLinkStatusResponse> {
  return request<TelegramLinkStatusResponse>("/telegram/status", {
    auth: true,
  });
}

export async function createTelegramLinkCode(): Promise<TelegramLinkCode> {
  return request<TelegramLinkCode>("/telegram/link", {
    method: "POST",
    auth: true,
  });
}

export async function unlinkTelegram(): Promise<TelegramLinkStatusResponse> {
  return request<TelegramLinkStatusResponse>("/telegram/unlink", {
    method: "POST",
    auth: true,
  });
}
