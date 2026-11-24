import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../services/api";
import {
  collectUpcomingReminders,
  findNextReminder,
  hasUnavailableUpcoming,
  listTreatments,
  type Reminder,
} from "../services/treatments";
import {
  confirmReminder,
  postponeReminder,
  type PostponeDelay,
} from "../services/reminders";
import { getCompliance, type ComplianceResponse } from "../services/stats";
import { formatInZone, localDateKey } from "../utils/user";
import {
  BellIcon,
  CalendarIcon,
  ChartIcon,
  ClockIcon,
  PillIcon,
} from "../components/icons";
import ApiErrorCard from "../components/ApiErrorCard";
import StatsSummary from "../components/StatsSummary";
import UpcomingReminders from "../components/UpcomingReminders";

// Inicio: saludo, proxima dosis real, dosis de hoy con confirmar y
// posponer, resumen de cumplimiento de los ultimos 30 dias y
// acciones rapidas.
//
// Fuente unica para las dosis: una sola llamada a
// GET /treatments?limit=200 (sin N+1); las tomas salen de
// `upcoming_reminders` (ventana de 72 horas) y nunca se calculan.
// El cumplimiento sale de GET /stats/compliance (ultimos 30 dias,
// sin agrupacion) y se muestra tal cual, sin recalcular porcentajes.
// Sin sesion valida (401), la pagina muestra los estados vacios.

type DosesState =
  | { kind: "loading" }
  | {
      kind: "ready";
      next: Reminder | null;
      today: Reminder[];
      unavailable: boolean;
    }
  | { kind: "empty" }
  | { kind: "error"; error: ApiError };

type ComplianceState =
  | { status: "loading" }
  | { status: "ready"; data: ComplianceResponse }
  | { status: "error" }
  | { status: "skipped" };

function todayLocal(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDays(dateStr: string, days: number): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!match) {
    return dateStr;
  }
  const date = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]) + days,
  );
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function DashboardPage() {
  const { user } = useAuth();
  const timezone = user?.timezone ?? "America/Bogota";
  const [doses, setDoses] = useState<DosesState>({ kind: "loading" });
  const [compliance, setCompliance] = useState<ComplianceState>({
    status: "loading",
  });
  const [success, setSuccess] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyReminderId, setBusyReminderId] = useState<number | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const firstName = user?.name.trim().split(/\s+/)[0] ?? "";
  const today = new Date().toLocaleDateString("es-CO", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  const load = useCallback(async () => {
    setDoses({ kind: "loading" });
    try {
      const treatments = await listTreatments();
      const reminders = collectUpcomingReminders(treatments);
      const todayKey = localDateKey(new Date().toISOString(), timezone);
      setDoses({
        kind: "ready",
        next: findNextReminder(treatments),
        today: reminders.filter(
          (reminder) =>
            localDateKey(reminder.scheduled_at, timezone) === todayKey,
        ),
        unavailable: hasUnavailableUpcoming(treatments),
      });
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        // Sin sesion valida no hay dosis que mostrar; la pagina
        // sigue funcionando (el 401 ya limpio los tokens).
        setDoses({ kind: "empty" });
      } else {
        setDoses({
          kind: "error",
          error:
            caught instanceof ApiError
              ? caught
              : new ApiError(0, "No se pudieron cargar tus dosis."),
        });
      }
    }
  }, [timezone]);

  useEffect(() => {
    void load();
  }, [load, reloadNonce]);

  useEffect(() => {
    let cancelled = false;
    setCompliance({ status: "loading" });
    getCompliance({
      from: addDays(todayLocal(), -29),
      to: addDays(todayLocal(), 1),
    })
      .then((data) => {
        if (!cancelled) {
          setCompliance({ status: "ready", data });
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          if (caught instanceof ApiError && caught.status === 401) {
            setCompliance({ status: "skipped" });
          } else {
            setCompliance({ status: "error" });
          }
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleConfirm(reminder: Reminder) {
    setBusyReminderId(reminder.id);
    setSuccess(null);
    setActionError(null);
    try {
      await confirmReminder(reminder.id);
      setSuccess(`«${reminder.medication.name}» marcada como tomada.`);
      setReloadNonce((n) => n + 1);
    } catch (caught) {
      setActionError(
        caught instanceof ApiError
          ? caught.message
          : "No se pudo confirmar la toma.",
      );
    } finally {
      setBusyReminderId(null);
    }
  }

  async function handlePostpone(reminder: Reminder, delay: PostponeDelay) {
    setBusyReminderId(reminder.id);
    setSuccess(null);
    setActionError(null);
    try {
      await postponeReminder(reminder.id, delay);
      setSuccess(
        `«${reminder.medication.name}» pospuesta ${delay} minutos.`,
      );
      setReloadNonce((n) => n + 1);
    } catch (caught) {
      setActionError(
        caught instanceof ApiError
          ? caught.message
          : "No se pudo posponer la toma.",
      );
    } finally {
      setBusyReminderId(null);
    }
  }

  return (
    <div>
      <p className="greeting">
        {firstName ? `Hola, ${firstName}` : "Hola"}
      </p>
      <p className="subtitle">
        {today}. Este es tu panel de DosisAlerta.
      </p>

      {doses.kind === "error" ? (
        <ApiErrorCard
          error={doses.error}
          resource="tus dosis"
          backTo="/tratamientos"
          backLabel="Ver tratamientos"
          onRetry={() => setReloadNonce((n) => n + 1)}
        />
      ) : (
        <section className="card next-dose">
          <p className="label">Próxima dosis</p>
          {doses.kind === "loading" ? (
            <h2>Buscando tu próxima dosis…</h2>
          ) : doses.kind === "ready" && doses.next ? (
            <>
              <h2>
                {doses.next.medication.name} {doses.next.dose_amount}{" "}
                {doses.next.dose_unit}
              </h2>
              <p>
                {formatInZone(doses.next.scheduled_at, timezone)}
                {" • "}
                {doses.next.treatment.title}
              </p>
              <Link
                to={`/tratamientos/${doses.next.treatment.id}`}
                className="btn-light"
              >
                Ver tratamiento
              </Link>
            </>
          ) : (
            <>
              <h2>Aún no tienes dosis programadas</h2>
              <p>
                Cuando tengas tratamientos con horarios, aquí aparecerá
                tu próxima dosis con su hora y su medicamento.
              </p>
              <Link to="/tratamientos" className="btn-light">
                Ver tratamientos
              </Link>
            </>
          )}
        </section>
      )}

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
        <Link to="/estadisticas" className="quick-action">
          <span className="qa-icon" aria-hidden="true">
            <ChartIcon size={24} />
          </span>
          Estadísticas
        </Link>
      </div>

      {doses.kind === "error" ? null : (
        <section className="card">
          <h2>Dosis de hoy</h2>
          {success ? <p className="success-box">{success}</p> : null}
          {actionError ? <p className="error">{actionError}</p> : null}
          {doses.kind === "loading" ? (
            <p className="hint">Cargando tus dosis de hoy…</p>
          ) : doses.kind === "empty" ? (
            <>
              <p>No tienes dosis programadas para hoy.</p>
              <Link className="btn-primary" to="/tratamientos">
                Ver tratamientos
              </Link>
            </>
          ) : (
            <>
              {doses.unavailable ? (
                <div className="warn-box">
                  <p>
                    No se pudieron cargar las próximas tomas de todos tus
                    tratamientos. Lo que ves abajo puede estar incompleto.
                  </p>
                </div>
              ) : null}
              {doses.today.length === 0 && !doses.unavailable ? (
                <>
                  <p>
                    No tienes dosis programadas para hoy. Cuando tengas
                    tratamientos con horarios, aquí aparecerán tus tomas
                    del día con sus horas.
                  </p>
                  <Link className="btn-primary" to="/tratamientos">
                    Ver tratamientos
                  </Link>
                </>
              ) : null}
              {doses.today.length === 0 && doses.unavailable ? (
                <>
                  <p>
                    No se pudo comprobar si tienes dosis para hoy. Vuelve
                    a intentarlo desde Tratamientos.
                  </p>
                  <Link className="btn-primary" to="/tratamientos">
                    Ver tratamientos
                  </Link>
                </>
              ) : null}
              {doses.today.length > 0 ? (
                <UpcomingReminders
                  reminders={doses.today}
                  timezone={timezone}
                  showTreatment
                  onConfirm={handleConfirm}
                  onPostpone={handlePostpone}
                  busyReminderId={busyReminderId}
                />
              ) : null}
            </>
          )}
          <p className="hint">
            <Link to="/recordatorios">
              Ver las próximas tomas de 72 horas
            </Link>
            .
          </p>
        </section>
      )}

      {compliance.status === "skipped" ? null : (
        <section className="card">
          <h2>Tu cumplimiento</h2>
          {compliance.status === "loading" ? (
            <p className="hint">Cargando tu cumplimiento…</p>
          ) : compliance.status === "error" ? (
            <>
              <p>No se pudo cargar tu cumplimiento.</p>
              <Link className="btn-primary" to="/estadisticas">
                Ver estadísticas
              </Link>
            </>
          ) : (
            <>
              <StatsSummary summary={compliance.data.summary} />
              {compliance.data.summary.scheduled === 0 ? (
                <p className="hint">
                  Aún no hay tomas programadas en los últimos 30 días.
                  Crea un tratamiento con horarios para ver tu
                  cumplimiento.
                </p>
              ) : null}
              <p>
                <Link to="/estadisticas">Ver estadísticas</Link>
              </p>
            </>
          )}
        </section>
      )}
    </div>
  );
}
