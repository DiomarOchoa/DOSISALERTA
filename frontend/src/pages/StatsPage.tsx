// Estadisticas de cumplimiento (Fase 8, Entrega 5).
// - Lee GET /stats/compliance con los filtros admitidos por el
//   backend: from/to (fechas YYYY-MM-DD en la zona del paciente),
//   medication_id, group_by (day, week, month, medication).
// - Vista por defecto: ultimos 30 dias, agrupado por dia.
// - La fecha "hasta" es el ultimo dia incluido: la consulta envia
//   el dia siguiente como "to" (el rango del backend es [from, to)).
// - Nunca calcula porcentajes: usa summary y groups tal cual.
// - compliance_percentage null -> "—", nunca 0 %.
// - Sin group_by, groups es null y solo se muestra el resumen.
// - Un grupo con scheduled=0 se muestra como "Sin dosis".
// - En agrupacion semanal se respeta el period_start del backend
//   aunque sea anterior al inicio del rango.

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../services/api";
import { listMedications, type Medication } from "../services/medications";
import {
  getCompliance,
  type ComplianceResponse,
  type GroupBy,
} from "../services/stats";
import { formatDateOnly, localDateKey, localDayLabel } from "../utils/user";
import ApiErrorCard from "../components/ApiErrorCard";
import StatsSummary from "../components/StatsSummary";
import StatsBarChart, { type ChartBar } from "../components/StatsBarChart";

type StatsState =
  | { status: "loading" }
  | {
      status: "ready";
      data: ComplianceResponse;
      // La agrupacion con la que se pidieron estos datos. La grafica
      // solo se dibuja cuando coincide con la agrupacion pedida:
      // si no, las etiquetas nuevas se dibujarian sobre los grupos
      // viejos (por ejemplo, 30 barras diarias como "semanas").
      groupBy: GroupByOption;
    }
  | { status: "error"; error: ApiError };

type GroupByOption = GroupBy | "";

const GROUP_TITLES: Record<GroupBy, string> = {
  day: "Evolución diaria",
  week: "Evolución semanal",
  month: "Evolución mensual",
  medication: "Cumplimiento por medicamento",
};

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

function monthLabel(periodStart: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(periodStart);
  if (!match) {
    return periodStart;
  }
  const date = new Date(Number(match[1]), Number(match[2]) - 1, 1);
  const text = date.toLocaleDateString("es-CO", {
    month: "long",
    year: "numeric",
  });
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// Etiqueta de medicamento en el filtro. Cuando dos medicamentos
// comparten nombre y detalles, se distingue por su ID (hay dos
// pares asi en los datos de prueba: Vitamina T3 prueba 7/10 y
// Paracetamol T3 prueba 6/9). El valor del filtro es siempre el
// medication_id.
function medicationLabel(medication: Medication): string {
  const details = [
    medication.presentation,
    medication.concentration,
    medication.unit,
  ]
    .filter(Boolean)
    .join(" · ");
  return details ? `${medication.name} (${details})` : medication.name;
}

function medicationOptions(medications: Medication[]): Medication[] {
  const counts = new Map<string, number>();
  for (const medication of medications) {
    const label = medicationLabel(medication);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return medications.map((medication) => ({
    ...medication,
    name:
      (counts.get(medicationLabel(medication)) ?? 0) > 1
        ? `${medicationLabel(medication)} · ID ${medication.id}`
        : medicationLabel(medication),
  }));
}

// Convierte los grupos del backend en barras de la grafica.
// Para medicamentos, la clave es el medication_id y el nombre
// duplicado se distingue con su ID, igual que en el filtro.
function buildBars(
  response: ComplianceResponse,
  groupBy: GroupBy,
  timezone: string,
): ChartBar[] {
  if (response.groups === null) {
    return [];
  }
  if (groupBy === "medication") {
    const counts = new Map<string, number>();
    for (const bucket of response.groups) {
      const name = bucket.medication_name ?? "";
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    return response.groups.map((bucket) => ({
      key: `med-${bucket.medication_id}`,
      label:
        (counts.get(bucket.medication_name ?? "") ?? 0) > 1
          ? `${bucket.medication_name} · ID ${bucket.medication_id}`
          : (bucket.medication_name ?? ""),
      percentage: bucket.compliance_percentage,
      scheduled: bucket.scheduled,
    }));
  }
  const todayKey = localDateKey(new Date().toISOString(), timezone);
  return response.groups.map((bucket) => {
    const start = bucket.period_start ?? "";
    if (groupBy === "week") {
      return {
        key: start,
        label: `Semana del ${formatDateOnly(start)}`,
        percentage: bucket.compliance_percentage,
        scheduled: bucket.scheduled,
      };
    }
    if (groupBy === "month") {
      return {
        key: start,
        label: monthLabel(start),
        percentage: bucket.compliance_percentage,
        scheduled: bucket.scheduled,
      };
    }
    return {
      key: start,
      label: localDayLabel(start, todayKey),
      percentage: bucket.compliance_percentage,
      scheduled: bucket.scheduled,
    };
  });
}

export default function StatsPage() {
  const { user } = useAuth();
  const timezone = user?.timezone ?? "America/Bogota";
  const [state, setState] = useState<StatsState>({ status: "loading" });
  const [formError, setFormError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);

  const [medications, setMedications] = useState<Medication[]>([]);
  const [fromDate, setFromDate] = useState(() => addDays(todayLocal(), -29));
  const [toDate, setToDate] = useState(() => todayLocal());
  const [medicationId, setMedicationId] = useState("");
  const [groupBy, setGroupBy] = useState<GroupByOption>("day");

  const filtersActive =
    medicationId !== "" ||
    groupBy !== "day" ||
    fromDate !== addDays(todayLocal(), -29) ||
    toDate !== todayLocal();

  useEffect(() => {
    listMedications(true)
      .then((active) =>
        listMedications(false).then((inactive) =>
          setMedications([...active, ...inactive]),
        ),
      )
      .catch(() => setMedications([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    // El backend exige from < to (422 si no); "hasta" es el ultimo
    // dia incluido, asi que desde y hasta iguales no son validos.
    if (fromDate >= toDate) {
      setFormError(
        "La fecha «desde» debe ser anterior a la fecha «hasta».",
      );
      return;
    }
    setFormError(null);
    setState({ status: "loading" });
    getCompliance({
      from: fromDate,
      to: addDays(toDate, 1),
      medication_id: medicationId === "" ? undefined : Number(medicationId),
      group_by: groupBy === "" ? undefined : groupBy,
    })
      .then((data) => {
        if (!cancelled) {
          setState({ status: "ready", data, groupBy });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ status: "error", error });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [fromDate, toDate, medicationId, groupBy, reloadNonce]);

  function clearFilters() {
    setFromDate(addDays(todayLocal(), -29));
    setToDate(todayLocal());
    setMedicationId("");
    setGroupBy("day");
  }

  // Mientras los datos no correspondan a la agrupacion pedida
  // (un cambio de filtro todavia sin respuesta), se muestra la
  // carga y no una grafica con etiquetas de una agrupacion y
  // grupos de otra.
  if (
    state.status === "loading" ||
    (state.status === "ready" && state.groupBy !== groupBy)
  ) {
    return (
      <div>
        <div className="page-head">
          <h2>Estadísticas</h2>
        </div>
        <div className="card">
          <p>Cargando tus estadísticas…</p>
        </div>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div>
        <div className="page-head">
          <h2>Estadísticas</h2>
        </div>
        <ApiErrorCard
          error={state.error}
          resource="estadísticas"
          backTo="/inicio"
          onRetry={() => setReloadNonce((value) => value + 1)}
        />
      </div>
    );
  }

  const data = state.data;
  const dataGroupBy = state.groupBy;
  const hasData = data.summary.scheduled > 0;
  const bars =
    hasData && dataGroupBy !== ""
      ? buildBars(data, dataGroupBy, timezone)
      : [];

  return (
    <div>
      <div className="page-head">
        <h2>Estadísticas</h2>
      </div>
      <p className="hint">
        Tu porcentaje de cumplimiento y su evolución. Los porcentajes
        los calcula el backend (gracia de 30 minutos) y nunca se
        promedian entre grupos.
      </p>

      <section className="card stats-filters">
        <div className="field-row">
          <label className="field">
            <span>Desde</span>
            <input
              id="stats-from"
              type="date"
              value={fromDate}
              onChange={(event) => setFromDate(event.target.value)}
            />
          </label>
          <label className="field">
            <span>Hasta</span>
            <input
              id="stats-to"
              type="date"
              value={toDate}
              onChange={(event) => setToDate(event.target.value)}
            />
          </label>
        </div>
        <div className="field-row">
          <label className="field">
            <span>Medicamento</span>
            <select
              id="stats-medication"
              value={medicationId}
              onChange={(event) => setMedicationId(event.target.value)}
            >
              <option value="">Todos los medicamentos</option>
              {medicationOptions(medications).map((medication) => (
                <option key={medication.id} value={medication.id}>
                  {medication.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Agrupación</span>
            <select
              id="stats-group-by"
              value={groupBy}
              onChange={(event) =>
                setGroupBy(event.target.value as GroupByOption)
              }
            >
              <option value="day">Por día</option>
              <option value="week">Por semana</option>
              <option value="month">Por mes</option>
              <option value="medication">Por medicamento</option>
              <option value="">Sin agrupación (solo resumen)</option>
            </select>
          </label>
        </div>
        {formError ? <p className="field-error">{formError}</p> : null}
        <button className="btn-ghost" onClick={clearFilters}>
          Limpiar filtros
        </button>
      </section>

      <StatsSummary summary={data.summary} />

      {!hasData ? (
        <section className="card">
          <h2>Sin datos en este periodo</h2>
          <p>
            No hay tomas programadas entre esas fechas con esos filtros.
            {filtersActive
              ? " Prueba ampliando el rango o quitando el filtro de medicamento."
              : " Crea un tratamiento con horarios para ver tu cumplimiento."}
          </p>
          {filtersActive ? (
            <button className="btn-ghost" onClick={clearFilters}>
              Limpiar filtros
            </button>
          ) : (
            <Link className="btn-primary" to="/tratamientos">
              Ver tratamientos
            </Link>
          )}
        </section>
      ) : data.groups === null ? (
        <p className="hint">
          Sin agrupación: solo se muestra el resumen. Elige una
          agrupación para ver la gráfica.
        </p>
      ) : (
        <section className="card">
          <h3>{dataGroupBy === "" ? "" : GROUP_TITLES[dataGroupBy]}</h3>
          <p className="hint">
            Cada barra es el porcentaje de cumplimiento. «Sin dosis»
            significa que no hubo tomas programadas en ese periodo.
          </p>
          <StatsBarChart bars={bars} />
        </section>
      )}
    </div>
  );
}
