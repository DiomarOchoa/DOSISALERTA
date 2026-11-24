import { useState, type FormEvent } from "react";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../services/api";
import { passwordTooLong } from "../services/auth";

// Formulario de registro (Fase 8, Entrega 1).
// Interfaz y validaciones de Jaider (conciliada 6/6 por hashes el
// 20 nov 2026): nombre 1-120, contrasena 8 caracteres minimo y
// 72 bytes UTF-8 maximo, zona horaria IANA. El envio ahora pasa
// por el AuthContext, que guarda los tokens y el usuario en un
// solo lugar.

// Zonas horarias IANA mas probables para los usuarios del proyecto.
// El backend valida que la zona exista; si no es valida, devuelve 422.
const TIMEZONES = [
  "America/Bogota",
  "America/Lima",
  "America/Mexico_City",
  "America/Santiago",
  "America/Argentina/Buenos_Aires",
  "America/New_York",
  "Europe/Madrid",
  "UTC",
];

export default function RegisterForm() {
  const { register } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [timezone, setTimezone] = useState("America/Bogota");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (name.trim().length < 1 || name.trim().length > 120) {
      setError("El nombre debe tener entre 1 y 120 caracteres.");
      return;
    }
    if (password.length < 8) {
      setError("La contraseña debe tener al menos 8 caracteres.");
      return;
    }
    if (passwordTooLong(password)) {
      setError("La contraseña es demasiado larga (máximo 72 bytes).");
      return;
    }
    setLoading(true);
    try {
      await register({
        name: name.trim(),
        email: email.trim(),
        password,
        timezone,
      });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Ocurrió un error inesperado.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="form">
      <div className="field">
        <label htmlFor="register-name">Nombre</label>
        <input
          id="register-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={120}
          autoComplete="name"
        />
      </div>
      <div className="field">
        <label htmlFor="register-email">Correo electrónico</label>
        <input
          id="register-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
        />
      </div>
      <div className="field">
        <label htmlFor="register-password">Contraseña</label>
        <input
          id="register-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="new-password"
        />
        <p className="hint">Mínimo 8 caracteres.</p>
      </div>
      <div className="field">
        <label htmlFor="register-timezone">Zona horaria</label>
        <select
          id="register-timezone"
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
        >
          {TIMEZONES.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </select>
      </div>
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={loading}>
        {loading ? "Creando cuenta..." : "Crear cuenta"}
      </button>
    </form>
  );
}
