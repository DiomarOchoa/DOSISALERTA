import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { formatDate, initials } from "../utils/user";

// Perfil (Fase 8, Entrega 1). Datos reales de GET /auth/me con el
// diseno AppSalud: heroe con iniciales, filas de datos, ayuda y
// cierre de sesion. La vista de perfil del trabajo de Jaider
// (Dashboard de autenticacion) es la base de esta pagina.
export default function ProfilePage() {
  const { user, logout } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);

  if (!user) {
    return null;
  }

  async function handleLogout() {
    setLoggingOut(true);
    await logout();
    setLoggingOut(false);
  }

  return (
    <div>
      <section className="card">
        <div className="profile-hero">
          <span className="avatar avatar-large" aria-hidden="true">
            {initials(user.name)}
          </span>
          <h2>{user.name}</h2>
          <p className="muted">{user.email}</p>
        </div>
        <div style={{ marginTop: "1rem" }}>
          <div className="profile-row">
            <span className="row-label">Zona horaria</span>
            <span className="row-value">{user.timezone}</span>
          </div>
          <div className="profile-row">
            <span className="row-label">Cuenta creada</span>
            <span className="row-value">
              {formatDate(user.created_at)}
            </span>
          </div>
          <div className="profile-row">
            <span className="row-label">Estado</span>
            <span className="row-value">
              {user.is_active ? "Activa" : "Inactiva"}
            </span>
          </div>
          <div className="profile-row">
            <span className="row-label">Sesión</span>
            <span className="row-value">Activa, se renueva sola</span>
          </div>
        </div>
      </section>

      <section className="card">
        <h2>Ayuda</h2>
        <p>Cómo usar DosisAlerta:</p>
        <ul>
          <li>
            Crea tu cuenta con nombre, correo y contraseña (mínimo 8
            caracteres).
          </li>
          <li>
            Inicia sesión: tu sesión se mantiene aunque cierres el
            navegador.
          </li>
          <li>
            Si el token de acceso expira, la aplicación lo renueva
            sola con tu sesión.
          </li>
          <li>Cierra sesión con el botón Salir de arriba.</li>
          <li>
            Si el backend no responde, pulsa “Comprobar backend” en
            Inicio y revisa que esté corriendo en el puerto 8000.
          </li>
        </ul>
      </section>

      <section className="card">
        <h2>Cerrar sesión</h2>
        <p className="muted">
          Tu sesión se cierra en este dispositivo. Puedes volver a
          entrar cuando quieras.
        </p>
        <button
          type="button"
          className="btn-ghost"
          onClick={handleLogout}
          disabled={loggingOut}
        >
          {loggingOut ? "Cerrando sesión..." : "Cerrar sesión"}
        </button>
      </section>
    </div>
  );
}
