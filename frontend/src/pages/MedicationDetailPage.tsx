// Detalle de un medicamento (Entrega 2).
// - GET /medications/{id}: el backend responde 404 si no existe y
//   403 si existe pero es de otro usuario; en ambos casos se muestra
//   el estado, nunca los datos de otra persona.
// - Edicion en linea con el mismo formulario de crear (solo se
//   envian los campos que cambiaron).
// - Desactivar pide confirmacion en linea. Tras desactivar, la
//   pantalla lo refleja (Inactivo) y explica que en esta version
//   no se puede reactivar desde la web (la API no lo permite).

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../services/api";
import {
  deactivateMedication,
  getMedication,
  type Medication,
} from "../services/medications";
import ApiErrorCard from "../components/ApiErrorCard";
import MedicationForm from "../components/MedicationForm";
import { formatDate } from "../utils/user";

export default function MedicationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const medId = Number(id);
  const [med, setMed] = useState<Medication | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [editing, setEditing] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const [deactivating, setDeactivating] = useState(false);

  async function load() {
    if (!Number.isInteger(medId)) {
      setError(new ApiError(404, "Este medicamento no existe."));
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setMed(await getMedication(medId));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, "No se pudo cargar el medicamento."),
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // Solo al entrar a la pagina (o cambiar de id).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [medId]);

  async function handleDeactivate() {
    if (!med) {
      return;
    }
    setDeactivating(true);
    setSuccess(null);
    try {
      const updated = await deactivateMedication(med.id);
      setMed(updated);
      setConfirmDeactivate(false);
      setSuccess(`«${updated.name}» se desactivó y pasó a Inactivos.`);
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
        <h2>Medicamento</h2>
        <p>Cargando el medicamento…</p>
      </section>
    );
  }

  if (error) {
    return <ApiErrorCard error={error} onRetry={load} />;
  }

  if (!med) {
    return <ApiErrorCard error={new ApiError(404, "Este medicamento no existe.")} />;
  }

  return (
    <>
      <div className="page-head">
        <h2>{med.name}</h2>
        <span
          className={med.is_active ? "badge badge-done" : "badge badge-pending"}
        >
          {med.is_active ? "Activo" : "Inactivo"}
        </span>
      </div>

      {success ? <p className="success-box">{success}</p> : null}

      {editing ? (
        <section className="card">
          <h2>Editar medicamento</h2>
          <MedicationForm
            initial={med}
            onSaved={(saved) => {
              setMed(saved);
              setEditing(false);
              setSuccess("Cambios guardados.");
            }}
            onCancel={() => setEditing(false)}
          />
        </section>
      ) : (
        <section className="card">
          <div className="profile-row">
            <span className="row-label">Presentación</span>
            <span className="row-value">{med.presentation ?? "—"}</span>
          </div>
          <div className="profile-row">
            <span className="row-label">Concentración</span>
            <span className="row-value">{med.concentration ?? "—"}</span>
          </div>
          <div className="profile-row">
            <span className="row-label">Unidad</span>
            <span className="row-value">{med.unit ?? "—"}</span>
          </div>
          <div className="profile-row">
            <span className="row-label">Notas</span>
            <span className="row-value">{med.notes ?? "—"}</span>
          </div>
          <div className="profile-row">
            <span className="row-label">Creado</span>
            <span className="row-value">{formatDate(med.created_at)}</span>
          </div>
          <div className="profile-row">
            <span className="row-label">Actualizado</span>
            <span className="row-value">{formatDate(med.updated_at)}</span>
          </div>

          <div className="confirm-actions" style={{ marginTop: "1rem" }}>
            {med.is_active ? (
              <Link
                className="btn-primary"
                to="/tratamientos/nuevo"
                state={{ medicationId: med.id }}
              >
                Crear tratamiento
              </Link>
            ) : null}
            <button type="button" onClick={() => setEditing(true)}>
              Editar
            </button>
            {med.is_active ? (
              <button
                type="button"
                className="btn-danger"
                onClick={() => setConfirmDeactivate(true)}
              >
                Desactivar
              </button>
            ) : null}
            <Link className="btn-ghost" to="/medicamentos">
              Volver
            </Link>
          </div>

          {!med.is_active ? (
            <p className="hint" style={{ marginTop: "1rem" }}>
              Desactivado. En esta versión no se puede reactivar desde la
              web.
            </p>
          ) : null}

          {confirmDeactivate ? (
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
                  onClick={handleDeactivate}
                >
                  {deactivating ? "Desactivando…" : "Sí, desactivar"}
                </button>
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => setConfirmDeactivate(false)}
                >
                  Cancelar
                </button>
              </div>
            </div>
          ) : null}
        </section>
      )}
    </>
  );
}
