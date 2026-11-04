import { useState } from "react";

// URL base de la API desde variables de entorno de Vite.
// En desarrollo se lee de frontend/.env (copiado de .env.example):
//   VITE_API_URL=http://localhost:8000/api/v1
// Si no hay .env, se usa el valor de desarrollo local.
const API_URL =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";

// El endpoint de salud versionado vive en <API_URL>/health cuando
// API_URL ya termina en /api/v1; si alguien configura otra base,
// se construye /api/v1/health a partir de ella.
function healthUrl(apiUrl: string): string {
  const base = apiUrl.replace(/\/$/, "");
  if (base.endsWith("/api/v1")) {
    return `${base}/health`;
  }
  return `${base}/api/v1/health`;
}

type HealthState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; version: string }
  | { kind: "error"; message: string };

export default function App() {
  const [health, setHealth] = useState<HealthState>({ kind: "idle" });

  async function checkBackend() {
    setHealth({ kind: "loading" });
    try {
      const response = await fetch(healthUrl(API_URL));
      if (!response.ok) {
        setHealth({
          kind: "error",
          message: `El backend respondio HTTP ${response.status}.`,
        });
        return;
      }
      const data: unknown = await response.json();
      if (
        typeof data === "object" &&
        data !== null &&
        "status" in data &&
        (data as { status: unknown }).status === "ok"
      ) {
        const version =
          "version" in data && typeof (data as { version: unknown }).version === "string"
            ? (data as { version: string }).version
            : "desconocida";
        setHealth({ kind: "ok", version });
      } else {
        setHealth({ kind: "error", message: "Respuesta inesperada del backend." });
      }
    } catch {
      // No se muestra el detalle tecnico del error de red: el mensaje
      // util para el usuario es que el backend no esta levantado.
      setHealth({
        kind: "error",
        message:
          "No se pudo contactar al backend. Comprueba que esta corriendo en el puerto 8000.",
      });
    }
  }

  return (
    <main className="container">
      <h1>DosisAlerta</h1>
      <p>
        Gestion y seguimiento de tratamientos medicos. Esta es la
        pantalla inicial de la Fase 1: todavia no hay inicio de sesion,
        medicamentos ni tratamientos. Esos modulos llegan en fases
        posteriores.
      </p>

      <section className="card">
        <h2>Estado del backend</h2>
        <p>
          API configurada: <code>{API_URL}</code>
        </p>
        <button type="button" onClick={checkBackend} disabled={health.kind === "loading"}>
          {health.kind === "loading" ? "Comprobando..." : "Comprobar backend"}
        </button>
        {health.kind === "ok" && (
          <p className="ok">Backend en linea (version {health.version}).</p>
        )}
        {health.kind === "error" && <p className="error">{health.message}</p>}
      </section>

      <section className="card">
        <h2>Que viene despues</h2>
        <ul>
          <li>Fase 2: modelos y base de datos PostgreSQL.</li>
          <li>Fase 3: registro e inicio de sesion.</li>
          <li>Fase 4: medicamentos, tratamientos y horarios.</li>
          <li>Fase 5: motor de recordatorios.</li>
          <li>Fase 6: bot de Telegram.</li>
        </ul>
      </section>
    </main>
  );
}
