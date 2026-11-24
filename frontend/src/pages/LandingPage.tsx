import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import {
  BellIcon,
  CalendarIcon,
  ChartIcon,
  UserIcon,
} from "../components/icons";

// Pagina publica de presentacion (landing) de DosisAlerta.
// Sin sesion: que es la aplicacion, sus funciones y como funciona,
// con acceso directo a crear cuenta e iniciar sesion. Con sesion,
// la raiz lleva al inicio de la aplicacion.
export default function LandingPage() {
  const { user } = useAuth();

  if (user) {
    return <Navigate to="/inicio" replace />;
  }

  return (
    <div className="landing">
      <header className="landing-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            +
          </span>
          DosisAlerta
        </div>
        <div className="landing-header-actions">
          <Link to="/login" className="btn-ghost">
            Entrar
          </Link>
          <Link to="/registro" className="btn-primary">
            Crear cuenta
          </Link>
        </div>
      </header>

      <section className="landing-hero">
        <h1>
          Tu medicina, <span>a tiempo</span>
        </h1>
        <p>
          Tus tratamientos, horarios y recordatorios en un solo lugar.
          DosisAlerta te avisa cuando toca cada toma y te muestra cómo
          vas con tu tratamiento.
        </p>
        <div className="landing-hero-actions">
          <Link to="/registro" className="btn-primary">
            Crear cuenta
          </Link>
          <Link to="/login" className="btn-ghost">
            Ya tengo cuenta
          </Link>
        </div>
      </section>

      <section className="landing-section">
        <h2>Todo para no olvidar ninguna dosis</h2>
        <div className="landing-features">
          <div className="feature-card">
            <span className="feature-icon" aria-hidden="true">
              <BellIcon size={24} />
            </span>
            <h3>Recordatorios</h3>
            <p>
              Avisos cuando toca cada toma, con la opción de confirmar o
              posponer 15, 30 o 60 minutos.
            </p>
          </div>
          <div className="feature-card">
            <span className="feature-icon" aria-hidden="true">
              <CalendarIcon size={24} />
            </span>
            <h3>Tratamientos y horarios</h3>
            <p>
              Crea tus tratamientos con sus medicamentos, dosis y
              horarios, día a día.
            </p>
          </div>
          <div className="feature-card">
            <span className="feature-icon" aria-hidden="true">
              <ChartIcon size={24} />
            </span>
            <h3>Cumplimiento</h3>
            <p>
              Ve tu porcentaje de tomas a tiempo y tu evolución por día,
              semana o mes.
            </p>
          </div>
          <div className="feature-card">
            <span className="feature-icon" aria-hidden="true">
              <UserIcon size={24} />
            </span>
            <h3>Cuidadores</h3>
            <p>
              Comparte tus tratamientos con un cuidador, con permisos
              claros y bajo tu control.
            </p>
          </div>
        </div>
      </section>

      <section className="landing-section">
        <h2>Cómo funciona</h2>
        <div className="landing-steps">
          <div className="step">
            <span className="step-number" aria-hidden="true">
              1
            </span>
            <h3>Crea tu cuenta</h3>
            <p>Regístrate con tu correo y tu zona horaria.</p>
          </div>
          <div className="step">
            <span className="step-number" aria-hidden="true">
              2
            </span>
            <h3>Registra tu tratamiento</h3>
            <p>Añade tus medicamentos, dosis y horarios.</p>
          </div>
          <div className="step">
            <span className="step-number" aria-hidden="true">
              3
            </span>
            <h3>Recibe tus avisos</h3>
            <p>Confirma cada toma desde la web o desde Telegram.</p>
          </div>
        </div>
        <p className="landing-note">
          También puedes recibir tus avisos por Telegram vinculando tu
          cuenta desde el bot.
        </p>
      </section>

      <section className="landing-cta">
        <h2>Empieza hoy</h2>
        <p>Crea tu cuenta y lleva tus tratamientos al día.</p>
        <Link to="/registro" className="btn-light">
          Crear cuenta
        </Link>
      </section>

      <p className="landing-footer">
        DosisAlerta · Programación Avanzada A1 · Universidad de La
        Guajira
      </p>
    </div>
  );
}
