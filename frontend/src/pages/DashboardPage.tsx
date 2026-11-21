import { useState } from "react";
import { Link } from "react-router-dom";
import { API_URL, healthUrl } from "../config";
import {
  BellIcon,
  CalendarIcon,
  ClockIcon,
  PillIcon,
} from "../components/icons";

// Inicio (andamio de la Entrega 0): saludo, comprobacion de salud
// y avance del proyecto. La proxima dosis real llega con la
// Entrega 3 (GET /treatments y la toma mas proxima de
// `upcoming_reminders`); sin tratamientos, la seccion lo dice
// con honestidad.

type HealthState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; version: string }
  | { kind: "error"; message: string };

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthState>({ kind: "idle" });
  const today = new Date().toLocaleDateString("es-CO", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

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
          "version" in data &&
          typeof (data as { version: unknown }).version === "string"
            ? (data as { version: string }).version
            : "desconocida";
        setHealth({ kind: "ok", version });
      } else {
        setHealth({
          kind: "error",
          message: "Respuesta inesperada del backend.",
        });
      }
    } catch {
      setHealth({
        kind: "error",
        message:
          "No se pudo contactar al backend. Comprueba que esta corriendo en el puerto 8000.",
      });
    }
  }

  return (
    <div>
      <p className="greeting">Hola</p>
      <p className="subtitle">
        {today}. Este es tu panel de DosisAlerta.
      </p>

      <section className="card next-dose">
        <p className="label">Próxima dosis</p>
        <h2>Aún no tienes dosis programadas</h2>
        <p>
          Cuando tengas tratamientos con horarios, aquí aparecerá
          tu próxima dosis con su hora y su medicamento.
        </p>
      </section>

      <div className="quick-actions">
        <Link to="/medicamentos" className="quick-action">
          <span className="qa-icon" aria-hidden="true">
            <PillIcon size={24} />
          </span>
          Medicamentos
        </Link>
        <Link to="/tratamientos" className="quick-action">
          <span className="qa-icon" aria-hidden="true">
            <CalendarIcon size={24} />
          </span>
          Tratamientos
        </Link>
        <Link to="/recordatorios" className="quick-action">
          <span className="qa-icon" aria-hidden="true">
            <BellIcon size={24} />
          </span>
          Recordatorios
        </Link>
        <Link to="/historial" className="quick-action">
          <span className="qa-icon" aria-hidden="true">
            <ClockIcon size={24} />
          </span>
          Historial
        </Link>
      </div>

      <section className="card">
        <h2>Estado del backend</h2>
        <p>
          API configurada: <code>{API_URL}</code>
        </p>
        <button
          type="button"
          onClick={checkBackend}
          disabled={health.kind === "loading"}
        >
          {health.kind === "loading" ? "Comprobando..." : "Comprobar backend"}
        </button>
        {health.kind === "ok" && (
          <p className="ok">Backend en linea (version {health.version}).</p>
        )}
        {health.kind === "error" && (
          <p className="error">{health.message}</p>
        )}
      </section>

      <section className="card">
        <h2>Avance del proyecto</h2>
        <ul className="phase-list">
          <li>
            <span>Fase 2: modelos y base de datos PostgreSQL.</span>
            <span className="badge badge-done">Hecha</span>
          </li>
          <li>
            <span>Fase 3: registro e inicio de sesión.</span>
            <span className="badge badge-done">Hecha</span>
          </li>
          <li>
            <span>Fase 4: medicamentos, tratamientos y horarios.</span>
            <span className="badge badge-done">Hecha</span>
          </li>
          <li>
            <span>Fase 5: motor de recordatorios.</span>
            <span className="badge badge-pending">Pendiente</span>
          </li>
          <li>
            <span>Fase 6: bot de Telegram.</span>
            <span className="badge badge-pending">Pendiente</span>
          </li>
          <li>
            <span>Fase 7: historial y estadísticas.</span>
            <span className="badge badge-pending">Pendiente</span>
          </li>
          <li>
            <span>Fase 8: aplicación web.</span>
            <span className="badge badge-progress">En desarrollo</span>
          </li>
        </ul>
      </section>
    </div>
  );
}
