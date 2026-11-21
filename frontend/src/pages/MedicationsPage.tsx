// Listado de medicamentos del usuario autenticado (Entrega 2).
// - El listado viene del backend (GET /medications, ordenado por
//   nombre). Filtro Activos/Inactivos con ?is_active.
// - La busqueda es local sobre la lista cargada: la API no ofrece
//   busqueda en el servidor, asi que no se finge una.
// - Desactivar es una operacion destructiva en la practica (el
//   backend la hace logica y la API actual no permite reactivar),
//   asi que siempre pide confirmacion en linea antes de ejecutarla.

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../services/api";
import {
  deactivateMedication,
  listMedications,
  type Medication,
} from "../services/medications";
import ApiErrorCard from "../components/ApiErrorCard";

type Filter = "activos" | "inactivos";

function matches(med: Medication, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) {
    return true;
  }
  const haystack = [med.name, med.presentation, med.concentration, med.unit]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(q);
}

export default function MedicationsPage() {
  const [items, setItems] = useState<Medication[]>([]);
  const [filter, setFilter] = useState<Filter>("activos");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [deactivating, setDeactivating] = useState(false);

  async function load(nextFilter: Filter) {
    setLoading(true);
    setError(null);
    try {
      const data = await listMedications(nextFilter === "activos");
      setItems(data);
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
    load(filter);
    // Solo al cambiar el filtro; la busqueda es local y no recarga.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const visible = items.filter((med) => matches(med, search));

  async function handleDeactivate(med: Medication) {
    setDeactivating(true);
    setSuccess(null);
    try {
      await deactivateMedication(med.id);
      setConfirmId(null);
      setSuccess(`«${med.name}» se desactivó y pasó a Inactivos.`);
      await load(filter);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, "No se pudo desactivar el medicamento."),
      );
    } finally {
      setDeactivating(false);
    }
  }

  if (loading) {
    return (
      <section className="card">
        <h2>Medicamentos</h2>
        <p>Cargando tus medicamentos…</p>
      </section>
    );
  }

  if (error) {
    return (
      <>
        <div className="page-head">
          <h2>Medicamentos</h2>
        </div>
        <ApiErrorCard error={error} onRetry={() => load(filter)} />
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <h2>Medicamentos</h2>
        <Link id="med-new" className="btn-primary" to="/medicamentos/nuevo">
          Nuevo medicamento
        </Link>
      </div>

      {success ? <p className="success-box">{success}</p> : null}

      <div className="filter-row">
        <div className="tabs" role="tablist" aria-label="Filtrar por estado">
          <button
            type="button"
            className={filter === "activos" ? "tab active" : "tab"}
            onClick={() => setFilter("activos")}
          >
            Activos
          </button>
          <button
            type="button"
            className={filter === "inactivos" ? "tab active" : "tab"}
            onClick={() => setFilter("inactivos")}
          >
            Inactivos
          </button>
        </div>
        <input
          id="med-search"
          className="search-input"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar por nombre o presentación…"
          aria-label="Buscar medicamentos"
        />
      </div>

      {items.length === 0 ? (
        <section className="card">
          <h2>
            {filter === "activos"
              ? "Aún no tienes medicamentos"
              : "No tienes medicamentos inactivos"}
          </h2>
          <p>
            {filter === "activos"
              ? "Crea tu primer medicamento para empezar a organizar tus tratamientos."
              : "Los medicamentos desactivados aparecen aquí."}
          </p>
          {filter === "activos" ? (
            <Link className="btn-primary" to="/medicamentos/nuevo">
              Crear tu primer medicamento
            </Link>
          ) : null}
        </section>
      ) : visible.length === 0 ? (
        <section className="card">
          <h2>Sin resultados</h2>
          <p>
            No hay medicamentos que coincidan con «{search.trim()}» en esta
            lista.
          </p>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => setSearch("")}
          >
            Limpiar búsqueda
          </button>
        </section>
      ) : (
        <ul className="med-list">
          {visible.map((med) => (
            <li key={med.id}>
              <div className="med-item" data-med-id={med.id}>
                <Link
                  className="med-link"
                  to={`/medicamentos/${med.id}`}
                >
                  <p className="med-name">{med.name}</p>
                  <p className="med-meta">
                    {[med.presentation, med.concentration, med.unit]
                      .filter(Boolean)
                      .join(" · ") || "Sin detalles"}
                  </p>
                </Link>
                <span
                  className={
                    med.is_active ? "badge badge-done" : "badge badge-pending"
                  }
                >
                  {med.is_active ? "Activo" : "Inactivo"}
                </span>
                {med.is_active ? (
                  <button
                    type="button"
                    className="btn-danger"
                    onClick={() => setConfirmId(med.id)}
                  >
                    Desactivar
                  </button>
                ) : null}
              </div>
              {confirmId === med.id ? (
                <div className="confirm-box">
                  <p>
                    ¿Desactivar «{med.name}»? Pasará a Inactivos y en esta
                    versión no se puede reactivar desde la web.
                  </p>
                  <div className="confirm-actions">
                    <button
                      type="button"
                      className="btn-danger"
                      disabled={deactivating}
                      onClick={() => handleDeactivate(med)}
                    >
                      {deactivating ? "Desactivando…" : "Sí, desactivar"}
                    </button>
                    <button
                      type="button"
                      className="btn-ghost"
                      onClick={() => setConfirmId(null)}
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
