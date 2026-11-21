import { NavLink, Outlet } from "react-router-dom";
import type { ComponentType } from "react";
import { HomeIcon } from "./icons";

// Diseno de la Fase 8, adoptado del prototipo AppSalud (18 nov):
// cabecera con marca y navegacion inferior fija, columna centrada
// estilo app movil. Version de la Entrega 0: sin autenticacion,
// la cabecera muestra solo la marca y la navegacion solo la
// seccion Inicio (las demas llegan con sus entregas).

type NavItem = {
  to: string;
  label: string;
  Icon: ComponentType<{ size?: number }>;
};

const NAV_ITEMS: NavItem[] = [
  { to: "/inicio", label: "Inicio", Icon: HomeIcon },
];

export function AppLayout() {
  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            +
          </span>
          DosisAlerta
        </div>
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
