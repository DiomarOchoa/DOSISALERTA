import { Navigate, NavLink } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import RegisterForm from "../components/RegisterForm";

// Registro (Fase 8, Entrega 1). Con sesion, redirige a Inicio;
// sin sesion, muestra el formulario de Jaider con las pestanas
// de acceso (estilo AppSalud).
export default function RegisterPage() {
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
      <RegisterForm />
    </section>
  );
}
