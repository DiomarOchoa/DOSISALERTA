import { Navigate, NavLink } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import LoginForm from "../components/LoginForm";

// Inicio de sesion (Fase 8, Entrega 1). Con sesion, redirige a
// Inicio; sin sesion, muestra el formulario de Jaider con las
// pestanas de acceso (estilo AppSalud). Si la restauracion de la
// sesion fallo por red, se muestra el error aqui.
export default function LoginPage() {
  const { user, error } = useAuth();

  if (user) {
    return <Navigate to="/inicio" replace />;
  }

  return (
    <section className="card auth-card">
      <div className="tabs">
        <NavLink
          to="/login"
          className={({ isActive }) => (isActive ? "tab active" : "tab")}
        >
          Iniciar sesión
        </NavLink>
        <NavLink
          to="/registro"
          className={({ isActive }) => (isActive ? "tab active" : "tab")}
        >
          Crear cuenta
        </NavLink>
      </div>
      {error && <p className="error">{error}</p>}
      <LoginForm />
    </section>
  );
}
