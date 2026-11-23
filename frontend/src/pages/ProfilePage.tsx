import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError, updateProfile } from "../services/auth";
import { formatDate, initials } from "../utils/user";

// Zonas horarias IANA que se ofrecen en el selector (RF03).
// America/Bogota es la zona por defecto del proyecto.
const TIMEZONES: { value: string; label: string }[] = [
  { value: "America/Bogota", label: "Bogotá (UTC-5)" },
  { value: "America/Lima", label: "Lima (UTC-5)" },
  { value: "America/Quito", label: "Quito (UTC-5)" },
  { value: "America/Panama", label: "Panamá (UTC-5)" },
  { value: "America/Caracas", label: "Caracas (UTC-4)" },
  { value: "America/Mexico_City", label: "Ciudad de México (UTC-6)" },
  { value: "America/New_York", label: "Nueva York (UTC-5/-4)" },
  { value: "America/Chicago", label: "Chicago (UTC-6/-5)" },
  { value: "America/Denver", label: "Denver (UTC-7/-6)" },
  { value: "America/Los_Angeles", label: "Los Ángeles (UTC-8/-7)" },
  { value: "America/Santiago", label: "Santiago (UTC-4/-3)" },
  { value: "America/Buenos_Aires", label: "Buenos Aires (UTC-3)" },
  { value: "America/Sao_Paulo", label: "São Paulo (UTC-3)" },
  { value: "Atlantic/Azores", label: "Azores (UTC-1)" },
  { value: "Europe/London", label: "Londres (UTC+0/+1)" },
  { value: "Europe/Madrid", label: "Madrid (UTC+1/+2)" },
  { value: "Europe/Paris", label: "París (UTC+1/+2)" },
  { value: "Africa/Cairo", label: "El Cairo (UTC+2)" },
  { value: "Asia/Dubai", label: "Dubái (UTC+4)" },
  { value: "Asia/Kolkata", label: "Calcuta (UTC+5:30)" },
  { value: "Asia/Shanghai", label: "Shanghái (UTC+8)" },
  { value: "Asia/Tokyo", label: "Tokio (UTC+9)" },
  { value: "Australia/Sydney", label: "Sídney (UTC+10/+11)" },
  { value: "Pacific/Auckland", label: "Auckland (UTC+12/+13)" },
];

// Perfil (Fase 8, Entrega 1). Datos reales de GET /auth/me con el
// diseno AppSalud: heroe con iniciales, filas de datos, ayuda y
// cierre de sesion. La vista de perfil del trabajo de Jaider
// (Dashboard de autenticacion) es la base de esta pagina.
// RF03 (Etapa 5): la zona horaria es configurable desde aqui
// (PATCH /auth/me); un cambio recalcula unicamente las tomas
// PENDIENTE futuras (RNF04).
export default function ProfilePage() {
  const { user, logout, refreshUser } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);
  const [timezone, setTimezone] = useState(
    user?.timezone ?? "America/Bogota",
  );
  const [savingTz, setSavingTz] = useState(false);
  const [tzSaved, setTzSaved] = useState(false);
  const [tzError, setTzError] = useState<string | null>(null);

  if (!user) {
    return null;
  }

  const timezoneChanged = timezone !== user.timezone;
  const timezoneOptions = TIMEZONES.some((z) => z.value === user.timezone)
    ? TIMEZONES
    : [{ value: user.timezone, label: user.timezone }, ...TIMEZONES];

  async function handleLogout() {
    setLoggingOut(true);
    await logout();
    setLoggingOut(false);
  }

  async function handleSaveTimezone() {
    if (!timezoneChanged || savingTz) {
      return;
    }
    setSavingTz(true);
    setTzError(null);
    setTzSaved(false);
    try {
      await updateProfile({ timezone });
      await refreshUser();
      setTzSaved(true);
    } catch (caught) {
      setTzError(
        caught instanceof ApiError
          ? caught.message
          : "No se pudo cambiar la zona horaria.",
      );
    } finally {
      setSavingTz(false);
    }
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
            <span className="row-value">
              <select
                id="profile-timezone"
                className="search-input"
                value={timezone}
                onChange={(e) => {
                  setTimezone(e.target.value);
                  setTzSaved(false);
                  setTzError(null);
                }}
                disabled={savingTz}
                aria-label="Zona horaria"
              >
                {timezoneOptions.map((z) => (
                  <option key={z.value} value={z.value}>
                    {z.label}
                  </option>
                ))}
              </select>
            </span>
          </div>
          <div className="profile-row">
            <span className="row-label" />
            <span className="row-value">
              <button
                type="button"
                className="btn-primary btn-small"
                onClick={() => void handleSaveTimezone()}
                disabled={!timezoneChanged || savingTz}
              >
                {savingTz ? "Guardando…" : "Guardar zona horaria"}
              </button>
            </span>
          </div>
          {tzSaved ? (
            <p className="success-box" style={{ marginTop: "0.5rem" }}>
              Zona horaria actualizada a {user.timezone}. Las próximas
              tomas se recalculan con la nueva zona.
            </p>
          ) : null}
          {tzError ? (
            <p className="error" style={{ marginTop: "0.5rem" }}>
              {tzError}
            </p>
          ) : null}
          <p className="hint">
            Las tomas ya confirmadas o perdidas no cambian; solo se
            recalculan las pendientes futuras.
          </p>
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
        <h2>Cuidadores</h2>
        <p className="muted">
          Invita a alguien de tu confianza para que te acompañe con
          tus medicamentos y tomas. Tú decides qué puede ver y hacer.
        </p>
        <Link className="btn-primary" to="/cuidadores">
          Gestionar cuidadores
        </Link>
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
