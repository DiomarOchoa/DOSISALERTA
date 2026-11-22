// Próximas tomas (Fase 8, Entrega 4): lista agregada de solo
// lectura con los recordatorios reales de todos los tratamientos
// activos del usuario, ordenados cronológicamente y agrupados por
// día local (Hoy / Mañana / fecha).
//
// Fuente única: una sola llamada a `GET /treatments?limit=200`
// (sin N+1). Cada fila muestra medicamento, dosis, hora en la zona
// horaria del usuario, estado (PENDIENTE o ENVIADA) y el nombre del
// tratamiento como enlace a su detalle. Nunca se calcula una toma:
// los recordatorios cubren 72 horas desde la creación o la última
// reanudación de cada tratamiento, y sin motor (Fase 5) la lista se
// vacía pasada esa ventana; el vacío lo dice con honestidad.
// Una sección `upcoming_reminders` ausente (D-1, sin permiso) se
// distingue de una lista vacía: ausente = no disponible.
// Confirmar y posponer tomas no existen en el backend (Fase 5):
// esta página no ofrece esas acciones.

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../services/api";
import {
  collectUpcomingReminders,
  hasUnavailableUpcoming,
  listTreatments,
  type Reminder,
} from "../services/treatments";
import UpcomingReminders from "../components/UpcomingReminders";
import ApiErrorCard from "../components/ApiErrorCard";
import { localDateKey, localDayLabel } from "../utils/user";

type RemindersState =
  | { kind: "loading" }
  | {
      kind: "ready";
      reminders: Reminder[];
      unavailable: boolean;
    }
  | { kind: "error"; error: ApiError };

export default function RemindersPage() {
  const { user } = useAuth();
  const timezone = user?.timezone ?? "America/Bogota";
  const [state, setState] = useState<RemindersState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    listTreatments()
      .then((treatments) => {
        if (cancelled) {
          return;
        }
        setState({
          kind: "ready",
          reminders: collectUpcomingReminders(treatments),
          unavailable: hasUnavailableUpcoming(treatments),
        });
      })
      .catch((caught) => {
        if (cancelled) {
          return;
        }
        if (caught instanceof ApiError) {
          setState({ kind: "error", error: caught });
        } else {
          setState({
            kind: "error",
            error: new ApiError(0, "No se pudieron cargar las próximas tomas."),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "loading") {
    return (
      <div>
        <div className="page-head">
          <h2>Próximas tomas</h2>
        </div>
        <p className="hint">Cargando tus próximas tomas…</p>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div>
        <div className="page-head">
          <h2>Próximas tomas</h2>
        </div>
        <ApiErrorCard
          error={state.error}
          resource="próximas tomas"
          backTo="/tratamientos"
          backLabel="Volver a Tratamientos"
        />
      </div>
    );
  }

  const todayKey = localDateKey(new Date().toISOString(), timezone);
  const groups = new Map<string, Reminder[]>();
  for (const reminder of state.reminders) {
    const key = localDateKey(reminder.scheduled_at, timezone);
    const list = groups.get(key) ?? [];
    list.push(reminder);
    groups.set(key, list);
  }
  const sortedGroups = [...groups.entries()].sort(([a], [b]) =>
    a < b ? -1 : a > b ? 1 : 0,
  );

  return (
    <div>
      <div className="page-head">
        <h2>Próximas tomas</h2>
      </div>
      <p className="hint">
        Tus dosis programadas de las próximas 72 horas, en tu zona
        horaria. Los recordatorios se generan al crear o reanudar un
        tratamiento; sin motor de recordatorios (Fase 5), la lista se
        vacía pasada esa ventana.
      </p>

      {state.unavailable ? (
        <div className="warn-box">
          <p>
            No se pudieron cargar las próximas tomas de todos tus
            tratamientos. Lo que ves abajo puede estar incompleto.
          </p>
        </div>
      ) : null}

      {state.reminders.length === 0 && !state.unavailable ? (
        <section className="card">
          <h2>Sin próximas tomas</h2>
          <p>
            No tienes dosis programadas en las próximas 72 horas. Los
            recordatorios se generan al crear un tratamiento o al
            reanudarlo; un tratamiento con inicio futuro tampoco tiene
            próximas tomas todavía.
          </p>
          <Link className="btn-primary" to="/tratamientos">
            Ver tratamientos
          </Link>
        </section>
      ) : null}

      {state.reminders.length === 0 && state.unavailable ? (
        <section className="card">
          <h2>Próximas tomas no disponibles</h2>
          <p>
            No se pudo comprobar si tienes próximas tomas. Vuelve a
            intentarlo desde Tratamientos.
          </p>
          <Link className="btn-primary" to="/tratamientos">
            Ver tratamientos
          </Link>
        </section>
      ) : null}

      {sortedGroups.map(([dayKey, reminders]) => (
        <section key={dayKey} className="day-group">
          <h3 className="day-title">
            {localDayLabel(dayKey, todayKey)}
          </h3>
          <UpcomingReminders
            reminders={reminders}
            timezone={timezone}
            showTreatment
          />
        </section>
      ))}
    </div>
  );
}
