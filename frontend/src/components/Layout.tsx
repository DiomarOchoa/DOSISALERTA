import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import type { ComponentType } from "react";
import { BellIcon, CalendarIcon, HomeIcon, PillIcon, UserIcon } from "./icons";
import { useAuth } from "../context/AuthContext";
import { initials } from "../utils/user";

// Diseno de la Fase 8, adoptado del prototipo AppSalud (18 nov):
// cabecera con marca, navegacion inferior fija con 5 secciones
// (Entrega 4: Recordatorios), columna centrada estilo app movil.
// Con sesion, la cabecera muestra el usuario y el boton Salir;
// sin sesion, el enlace Entrar (Entrega 1).

type NavItem = {
  to: string;
  label: string;
  Icon: ComponentType<{ size?: number }>;
};

const NAV_ITEMS: NavItem[] = [
  { to: "/inicio", label: "Inicio", Icon: HomeIcon },
  { to: "/medicamentos", label: "Medicamentos", Icon: PillIcon },
  { to: "/tratamientos", label: "Tratamientos", Icon: CalendarIcon },
  { to: "/recordatorios", label: "Recordatorios", Icon: BellIcon },
  { to: "/perfil", label: "Perfil", Icon: UserIcon },
];

export function AppLayout() {
  const { user, logout } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    setLoggingOut(true);
    await logout();
    setLoggingOut(false);
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            +
          </span>
          DosisAlerta
        </div>
        {user ? (
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <div className="user-chip">
              <span className="avatar" aria-hidden="true">
                {initials(user.name)}
              </span>
              <div className="user-meta">
                <div className="name">{user.name}</div>
                <div className="email">{user.email}</div>
              </div>
            </div>
            <button
              type="button"
              className="btn-ghost"
              onClick={handleLogout}
              disabled={loggingOut}
            >
              {loggingOut ? "Saliendo..." : "Salir"}
            </button>
          </div>
        ) : (
          <NavLink to="/login" className="btn-ghost">
            Entrar
          </NavLink>
        )}
      </header>

      <main>
        <Outlet />
        <p className="site-footer">
          DosisAlerta · Programación Avanzada A1 · Universidad de La
          Guajira
        </p>
      </main>

      <nav className="bottom-nav" aria-label="Navegación principal">
        <div className="bottom-nav-inner">
          {NAV_ITEMS.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                isActive ? "nav-item active" : "nav-item"
              }
            >
              <Icon size={22} />
              <span>{label}</span>
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}

// Paginas publicas (sin sesion): bienvenida centrada, sin
// navegacion inferior. La tarjeta de acceso vive en cada pagina.
export function PublicLayout() {
  return (
    <div className="auth-page">
      <div className="welcome-mark" aria-hidden="true">
        +
      </div>
      <h1 className="welcome-title">
        Tu medicina, <span>a tiempo</span>
      </h1>
      <p className="welcome-sub">
        Tu salud es lo primero. Lleva tus tratamientos al día con
        DosisAlerta.
      </p>
      <Outlet />
      <p className="auth-foot">
        DosisAlerta · Programación Avanzada A1 · Universidad de La
        Guajira
      </p>
    </div>
  );
}
