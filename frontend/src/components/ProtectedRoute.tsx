import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

// Guarda de las rutas privadas (Fase 8, Entrega 1).
// Mientras se restaura la sesion, muestra una espera; sin usuario,
// redirige a /login. Las rutas publicas (/login, /registro) quedan
// fuera de este guarda.
export default function ProtectedRoute() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="auth-page">
        <p className="muted">Cargando tu sesión...</p>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
