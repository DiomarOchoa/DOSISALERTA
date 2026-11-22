import { Link } from "react-router-dom";

// Ruta no encontrada (cualquier URL fuera de las definidas).
export default function NotFoundPage() {
  return (
    <section className="card">
      <h2>Página no encontrada</h2>
      <p>Esta página no existe en DosisAlerta.</p>
      <p>
        <Link to="/inicio">Volver al inicio</Link>
      </p>
    </section>
  );
}
