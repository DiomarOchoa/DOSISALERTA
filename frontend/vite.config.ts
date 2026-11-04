import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Configuracion minima de Vite para la Fase 1.
// - Puerto 5173, el mismo que espera el CORS del backend.
// - Sin proxy: el frontend llama directamente a VITE_API_URL.
//   En desarrollo eso es http://localhost:8000/api/v1 (ver .env.example).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
