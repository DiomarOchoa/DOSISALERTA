// Crear un tratamiento (Entrega 3).
// Carga los medicamentos activos para el selector del formulario.
// Sin medicamentos activos no se puede crear un tratamiento: el
// backend exige al menos uno.

import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../services/api";
import { listMedications, type Medication } from "../services/medications";
import ApiErrorCard from "../components/ApiErrorCard";
import TreatmentForm from "../components/TreatmentForm";

export default function TreatmentCreatePage() {
  const navigate = useNavigate();
  const [medications, setMedications] = useState<Medication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;
    listMedications(true)
      .then((data) => {
        if (!cancelled) {
          setMedications(data);
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(
            caught instanceof ApiError
              ? caught
              : new ApiError(0, "No se pudieron cargar los medicamentos."),
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <section className="card">
        <h2>Nuevo tratamiento</h2>
        <p>Cargando tus medicamentos…</p>
      </section>
    );
  }

  if (error) {
    return (
      <>
        <div className="page-head">
          <h2>Nuevo tratamiento</h2>
        </div>
        <ApiErrorCard error={error} onRetry={() => window.location.reload()} />
      </>
    );
  }

  if (medications.length === 0) {
    return (
      <>
        <div className="page-head">
          <h2>Nuevo tratamiento</h2>
        </div>
        <section className="card">
          <h2>Primero necesitas un medicamento activo</h2>
          <p>
            Un tratamiento se crea con al menos un medicamento y un
            horario. Todavía no tienes medicamentos activos.
          </p>
          <Link className="btn-primary" to="/medicamentos/nuevo">
            Crear tu primer medicamento
          </Link>
        </section>
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <h2>Nuevo tratamiento</h2>
        <Link className="btn-ghost" to="/tratamientos">
          Volver
        </Link>
      </div>
      <section className="card">
        <TreatmentForm
          medications={medications}
          onSaved={(created) => navigate(`/tratamientos/${created.id}`)}
          onCancel={() => navigate("/tratamientos")}
        />
      </section>
    </>
  );
}
