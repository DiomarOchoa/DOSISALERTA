// Listado de tratamientos del usuario autenticado (Entrega 3).
// - Una sola carga: GET /treatments?limit=200 (ordenado por
//   start_date DESC). La respuesta ya trae las secciones anidadas
//   completas, asi que pedirla por estado no la aligera: el filtro
//   por estado y la busqueda por titulo son locales.
// - Cada fila muestra su proxima toma real (la menor
//   `scheduled_at` de sus `upcoming_reminders`); si no hay, lo dice
//   en lugar de calcularla.

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../services/api";
import {
  findNextReminder,
  listTreatments,
  type Treatment,
  type TreatmentStatus,
} from "../services/treatments";
import ApiErrorCard from "../components/ApiErrorCard";
import { useAuth } from "../context/AuthContext";
import { formatDateOnly, formatInZone } from "../utils/user";

type Filter = "TODOS" | TreatmentStatus;

export const STATUS_LABEL: Record<TreatmentStatus, string> = {
  ACTIVO: "Activo",
  PAUSADO: "Pausado",
  COMPLETADO: "Completado",
  CANCELADO: "Cancelado",
};

export const STATUS_BADGE: Record<TreatmentStatus, string> = {
  ACTIVO: "badge badge-done",
  PAUSADO: "badge badge-progress",
  COMPLETADO: "badge badge-done",
  CANCELADO: "badge badge-pending",
};

const FILTERS: { key: Filter; label: string }[] = [
  { key: "TODOS", label: "Todos" },
  { key: "ACTIVO", label: "Activos" },
  { key: "PAUSADO", label: "Pausados" },
  { key: "COMPLETADO", label: "Completados" },
  { key: "CANCELADO", label: "Cancelados" },
];

export default function TreatmentsPage() {
  const { user } = useAuth();
  const timezone = user?.timezone ?? "America/Bogota";
  const [items, setItems] = useState<Treatment[]>([]);
  const [filter, setFilter] = useState<Filter>("TODOS");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setItems(await listTreatments());
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, "No se pudo cargar la lista."),
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // Solo al entrar a la pagina.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visible = items.filter((treatment) => {
    if (filter !== "TODOS" && treatment.status !== filter) {
      return false;
    }
    const query = search.trim().toLowerCase();
    if (!query) {
      return true;
    }
    return treatment.title.toLowerCase().includes(query);
  });

  if (loading) {
    return (
      <section className="card">
        <h2>Tratamientos</h2>
        <p>Cargando tus tratamientos…</p>
      </section>
    );
  }

  if (error) {
    return (
      <>
        <div className="page-head">
          <h2>Tratamientos</h2>
        </div>
        <ApiErrorCard
          error={error}
          onRetry={load}
          resource="tratamiento"
          backTo="/tratamientos"
          backLabel="Volver a Tratamientos"
        />
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <h2>Tratamientos</h2>
        <Link id="trt-new" className="btn-primary" to="/tratamientos/nuevo">
          Nuevo tratamiento
        </Link>
      </div>

      <div className="filter-row">
        <div className="tabs" role="tablist" aria-label="Filtrar por estado">
          {FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={filter === item.key ? "tab active" : "tab"}
              onClick={() => setFilter(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <input
          id="trt-search"
          className="search-input"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar por título…"
          aria-label="Buscar tratamientos"
        />
      </div>

      {items.length === 0 ? (
        <section className="card">
          <h2>Aún no tienes tratamientos</h2>
          <p>
            Crea tu primer tratamiento con sus medicamentos y horarios
            para empezar a organizar tus tomas.
          </p>
          <Link className="btn-primary" to="/tratamientos/nuevo">
            Crear tu primer tratamiento
          </Link>
        </section>
      ) : visible.length === 0 ? (
        <section className="card">
          <h2>Sin resultados</h2>
          <p>
            No hay tratamientos que coincidan con esa búsqueda o ese
            estado.
          </p>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => {
              setSearch("");
              setFilter("TODOS");
            }}
          >
            Limpiar filtros
          </button>
        </section>
      ) : (
        <ul className="med-list">
          {visible.map((treatment) => {
            const next = findNextReminder([treatment]);
            const medCount = (treatment.medications ?? []).filter(
              (link) => link.is_active,
            ).length;
            return (
              <li key={treatment.id}>
                <div className="med-item" data-trt-id={treatment.id}>
                  <Link
                    className="med-link"
                    to={`/tratamientos/${treatment.id}`}
                  >
                    <p className="med-name">{treatment.title}</p>
                    <p className="med-meta">
                      {formatDateOnly(treatment.start_date)}
                      {treatment.end_date
                        ? ` – ${formatDateOnly(treatment.end_date)}`
                        : ""}
                      {` · ${medCount} medicamento${medCount === 1 ? "" : "s"}`}
                    </p>
                    <p className="med-meta">
                      {next
                        ? `Próxima toma: ${next.medication.name}, ${formatInZone(next.scheduled_at, timezone)}`
                        : "Sin próximas tomas"}
                    </p>
                  </Link>
                  <span className={STATUS_BADGE[treatment.status]}>
                    {STATUS_LABEL[treatment.status]}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
