// Historial de tomas (Fase 8, Entrega 5).
// - Lee GET /reminders/history con los filtros admitidos por el
//   backend: from/to (datetimes sobre scheduled_at), medication_id,
//   treatment_id, status (un solo estado) y paginacion limit/offset.
// - Vista por defecto: ultimos 30 dias. Orden: el del backend
//   (scheduled_at DESC, id DESC), agrupado por dia local.
// - Nunca calcula tomas ni porcentajes: muestra el estado
//   almacenado tal cual lo devuelve el backend.
// - Paginacion real con "Cargar mas" (limit 50, offset = registros
//   ya cargados) y total de registros.
// - Los filtros de medicamento y tratamiento se cargan de la API;
//   si esa carga falla, el historial sigue funcionando con fechas
//   y estado.

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../services/api";
import {
  getHistory,
  type HistoryItem,
  type ReminderStatus,
} from "../services/history";
import { listMedications, type Medication } from "../services/medications";
import { listTreatments, type Treatment } from "../services/treatments";
import ApiErrorCard from "../components/ApiErrorCard";
import HistoryRow from "../components/HistoryRow";
import { localDateKey, localDayLabel } from "../utils/user";

const PAGE_SIZE = 50;

const ALL_STATUSES: ReminderStatus[] = [
  "PENDIENTE",
  "ENVIANDO",
  "ENVIADA",
  "TOMADA",
  "POSPUESTA",
  "PERDIDA",
  "CANCELADA",
  "FALLIDA",
];

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

// Inicio de un dia local como datetime ISO (UTC), para el filtro
// from/to del backend, que usa [from, to) sobre scheduled_at.
function localDayStartIso(dateStr: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!match) {
    return dateStr;
  }
  return new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
  ).toISOString();
}

// Etiqueta de un medicamento en el filtro. Dos medicamentos pueden
// compartir nombre (verificado en la Etapa 0): se anaden
// presentacion, concentracion y unidad cuando existen. Si aun asi
// dos etiquetas coinciden (en los datos reales hay dos "Vitamina
// T3 prueba" identicas en todo salvo el id), se anade el id para
// que cada opcion sea distinguible. El valor es siempre el id.
function medicationLabel(med: Medication): string {
  const details = [med.presentation, med.concentration, med.unit]
    .filter(Boolean)
    .join(" · ");
  return details ? `${med.name} (${details})` : med.name;
}

function medicationOptions(
  meds: Medication[],
): { id: number; label: string }[] {
  const base = meds.map((med) => ({ id: med.id, label: medicationLabel(med) }));
  const counts = new Map<string, number>();
  for (const option of base) {
    counts.set(option.label, (counts.get(option.label) ?? 0) + 1);
  }
  return base.map((option) =>
    (counts.get(option.label) ?? 0) > 1
      ? { id: option.id, label: `${option.label} · ID ${option.id}` }
      : option,
  );
}

export default function HistoryPage() {
  const { user } = useAuth();
  const timezone = user?.timezone ?? "America/Bogota";
  const [defaultFrom] = useState(() => addDays(todayLocal(), -29));
  const [defaultTo] = useState(() => todayLocal());
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [fromDate, setFromDate] = useState(defaultFrom);
  const [toDate, setToDate] = useState(defaultTo);
  const [status, setStatus] = useState("");
  const [medicationId, setMedicationId] = useState("");
  const [treatmentId, setTreatmentId] = useState("");
  const [medications, setMedications] = useState<Medication[]>([]);
  const [treatments, setTreatments] = useState<Treatment[]>([]);

  const filtersActive =
    status !== "" ||
    medicationId !== "" ||
    treatmentId !== "" ||
    fromDate !== defaultFrom ||
    toDate !== defaultTo;

  // Firma de los filtros actuales: si cambian mientras se carga
  // otra pagina, esa respuesta se descarta en lugar de mezclar
  // filas de un filtro con las de otro.
  const filterSignature = `${fromDate}|${toDate}|${status}|${medicationId}|${treatmentId}`;
  const filterSignatureRef = useRef(filterSignature);
  useEffect(() => {
    filterSignatureRef.current = filterSignature;
  });

  function buildFilters(offset: number) {
    return {
      from: localDayStartIso(fromDate),
      to: localDayStartIso(addDays(toDate, 1)),
      status: status === "" ? undefined : (status as ReminderStatus),
      medication_id:
        medicationId === "" ? undefined : Number(medicationId),
      treatment_id:
        treatmentId === "" ? undefined : Number(treatmentId),
      limit: PAGE_SIZE,
      offset,
    };
  }

  // Opciones de los filtros (una sola vez). Activos e inactivos:
  // el historial de un medicamento desactivado tambien se puede
  // filtrar por el.
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listMedications(true),
      listMedications(false),
      listTreatments(),
    ])
      .then(([activos, inactivos, allTreatments]) => {
        if (cancelled) {
          return;
        }
        const all = [...activos, ...inactivos].sort((a, b) =>
          a.name.localeCompare(b.name, "es-CO"),
        );
        setMedications(all);
        setTreatments(allTreatments);
      })
      .catch(() => {
        // Sin opciones, los selectores quedan en "Todos" y el
        // historial sigue funcionando con fechas y estado.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (fromDate > toDate) {
      setFormError(
        "La fecha «desde» debe ser anterior o igual a la fecha «hasta».",
      );
      return;
    }
    setFormError(null);
    setLoadMoreError(null);
    let cancelled = false;
    setLoading(true);
    setError(null);
    getHistory(buildFilters(0))
      .then((page) => {
        if (cancelled) {
          return;
        }
        setItems(page.items);
        setTotal(page.total);
      })
      .catch((caught) => {
        if (cancelled) {
          return;
        }
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError(0, "No se pudo cargar el historial."),
        );
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // buildFilters se recrea en cada render; los filtros que
    // importan estan en las dependencias.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromDate, toDate, status, medicationId, treatmentId, reloadNonce]);

  async function loadMore() {
    if (loadingMore || items.length >= total) {
      return;
    }
    const signature = filterSignature;
    setLoadingMore(true);
    setLoadMoreError(null);
    try {
      const page = await getHistory(buildFilters(items.length));
      if (filterSignatureRef.current !== signature) {
        return;
      }
      setItems((current) => [...current, ...page.items]);
      setTotal(page.total);
    } catch (caught) {
      setLoadMoreError(
        caught instanceof ApiError
          ? caught.message
          : "No se pudieron cargar más registros.",
      );
    } finally {
      setLoadingMore(false);
    }
  }

  function clearFilters() {
    setFromDate(defaultFrom);
    setToDate(defaultTo);
    setStatus("");
    setMedicationId("");
    setTreatmentId("");
  }

  if (loading) {
    return (
      <section className="card">
        <h2>Historial</h2>
        <p>Cargando tu historial…</p>
      </section>
    );
  }

  if (error) {
    return (
      <div>
        <div className="page-head">
          <h2>Historial</h2>
        </div>
        <ApiErrorCard
          error={error}
          onRetry={() => setReloadNonce((n) => n + 1)}
          resource="historial"
          backTo="/inicio"
          backLabel="Volver a Inicio"
        />
      </div>
    );
  }

  const todayKey = localDateKey(new Date().toISOString(), timezone);
  const groups = new Map<string, HistoryItem[]>();
  for (const item of items) {
    const key = localDateKey(item.scheduled_at, timezone);
    const list = groups.get(key) ?? [];
    list.push(item);
    groups.set(key, list);
  }
  const sortedGroups = [...groups.entries()].sort(([a], [b]) =>
    a > b ? -1 : a < b ? 1 : 0,
  );

  return (
    <div>
      <div className="page-head">
        <h2>Historial</h2>
      </div>
      <p className="hint">
        Tus tomas programadas y registradas, en tu zona horaria. El
        rango incluye el día «hasta» completo. Las dosis futuras
        aparecen cuando ya están generadas (72 horas).
      </p>

      <section className="card history-filters">
        <div className="field-row">
          <div className="field">
            <label htmlFor="history-from">Desde</label>
            <input
              id="history-from"
              type="date"
              value={fromDate}
              onChange={(event) => setFromDate(event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="history-to">Hasta</label>
            <input
              id="history-to"
              type="date"
              value={toDate}
              onChange={(event) => setToDate(event.target.value)}
            />
          </div>
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="history-status">Estado</label>
            <select
              id="history-status"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="">Todos los estados</option>
              {ALL_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {value.charAt(0) + value.slice(1).toLowerCase()}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="history-medication">Medicamento</label>
            <select
              id="history-medication"
              value={medicationId}
              onChange={(event) => setMedicationId(event.target.value)}
            >
              <option value="">Todos los medicamentos</option>
              {medicationOptions(medications).map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label htmlFor="history-treatment">Tratamiento</label>
          <select
            id="history-treatment"
            value={treatmentId}
            onChange={(event) => setTreatmentId(event.target.value)}
          >
            <option value="">Todos los tratamientos</option>
            {treatments.map((treatment) => (
              <option key={treatment.id} value={treatment.id}>
                {treatment.title}
              </option>
            ))}
          </select>
        </div>
        {formError ? <p className="field-error">{formError}</p> : null}
        <div className="load-more">
          <button
            type="button"
            className="btn-ghost"
            onClick={clearFilters}
          >
            Limpiar filtros
          </button>
        </div>
      </section>

      {items.length === 0 && !filtersActive ? (
        <section className="card">
          <h2>Aún no tienes historial</h2>
          <p>
            Cuando tengas tratamientos con horarios, aquí aparecerán
            tus tomas programadas y registradas.
          </p>
          <Link className="btn-primary" to="/tratamientos">
            Ver tratamientos
          </Link>
        </section>
      ) : null}

      {items.length === 0 && filtersActive ? (
        <section className="card">
          <h2>Sin registros en este periodo</h2>
          <p>No hay tomas entre esas fechas con esos filtros.</p>
          <button
            type="button"
            className="btn-ghost"
            onClick={clearFilters}
          >
            Limpiar filtros
          </button>
        </section>
      ) : null}

      {items.length > 0 ? (
        <p className="hint">
          Mostrando {items.length} de {total} registros
        </p>
      ) : null}

      {sortedGroups.map(([dayKey, dayItems]) => (
        <section key={dayKey} className="day-group">
          <h3 className="day-title">{localDayLabel(dayKey, todayKey)}</h3>
          <ul className="upcoming-list">
            {dayItems.map((item) => (
              <HistoryRow key={item.id} item={item} timezone={timezone} />
            ))}
          </ul>
        </section>
      ))}

      {items.length > 0 && items.length < total ? (
        <div className="load-more">
          <button
            type="button"
            className="btn-ghost"
            disabled={loadingMore}
            onClick={loadMore}
          >
            {loadingMore ? "Cargando…" : "Cargar más"}
          </button>
        </div>
      ) : null}

      {loadMoreError ? (
        <div className="load-more">
          <p className="error">{loadMoreError}</p>
          <button type="button" className="btn-ghost" onClick={loadMore}>
            Reintentar
          </button>
        </div>
      ) : null}
    </div>
  );
}
