// Crear un medicamento (Entrega 2).
// Tras guardarlo, se abre su detalle. Sin datos simulados: si la
// API falla, el formulario muestra el error del servidor.

import { useNavigate } from "react-router-dom";
import MedicationForm from "../components/MedicationForm";

export default function MedicationCreatePage() {
  const navigate = useNavigate();

  return (
    <section className="card">
      <h2>Nuevo medicamento</h2>
      <p className="muted">
        Registra un medicamento de tu catálogo propio. Luego podrás
        usarlo en tus tratamientos.
      </p>
      <MedicationForm
        onSaved={(med) => navigate(`/medicamentos/${med.id}`)}
        onCancel={() => navigate("/medicamentos")}
      />
    </section>
  );
}
