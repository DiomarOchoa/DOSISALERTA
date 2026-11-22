// Tarjeta de error de la API para las pantallas de medicamentos y
// de tratamientos. Traduce el estado HTTP a un mensaje honesto,
// sin inventar datos:
// - 401: la sesion expiro (el cliente ya intento renovarla una vez).
// - 403: el recurso existe pero es de otro usuario (o sin permiso).
// - 404: el recurso no existe.
// - 0: no hay conexion con el backend.
// - resto: el mensaje que devolvio el backend.
// Los textos por defecto son los de medicamentos; las paginas de
// tratamientos pasan `resource`, `backTo` y `backLabel`.

import { Link } from "react-router-dom";
import { ApiError } from "../services/api";

export default function ApiErrorCard({
  error,
  onRetry,
  resource = "medicamento",
  backTo = "/medicamentos",
  backLabel = "Volver a Medicamentos",
}: {
  error: ApiError;
  onRetry?: () => void;
  resource?: string;
  backTo?: string;
  backLabel?: string;
}) {
  if (error.status === 401) {
    return (
      <section className="card">
        <h2>Sesión expirada</h2>
        <p>Tu sesión expiró. Inicia sesión de nuevo para seguir.</p>
        <Link className="btn-primary" to="/login">
          Iniciar sesión
        </Link>
      </section>
    );
  }

  if (error.status === 403) {
    return (
      <section className="card">
        <h2>Sin permiso</h2>
        <p>
          No tienes permiso para ver o cambiar este contenido. Si es un{" "}
          {resource} de otra persona, no se muestra.
        </p>
        <Link className="btn-primary" to={backTo}>
          {backLabel}
        </Link>
      </section>
    );
  }

  if (error.status === 404) {
    return (
      <section className="card">
        <h2>No encontrado</h2>
        <p>Este {resource} no existe.</p>
        <Link className="btn-primary" to={backTo}>
          {backLabel}
        </Link>
      </section>
    );
  }

  if (error.status === 0) {
    return (
      <section className="card">
        <h2>Sin conexión</h2>
        <p>{error.message}</p>
        {onRetry ? (
          <button type="button" onClick={onRetry}>
            Reintentar
          </button>
        ) : null}
      </section>
    );
  }

  return (
    <section className="card">
      <h2>Algo salió mal</h2>
      <p className="error">{error.message}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Reintentar
        </button>
      ) : null}
    </section>
  );
}
