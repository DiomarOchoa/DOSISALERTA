import type { ReactNode } from "react";

// Tarjeta generica para los modulos que aun no tienen pantalla.
// Dice claramente en que entrega llega y que no hay datos.
// (Adaptado del ModuleSoon del prototipo AppSalud.)
export default function ModuleSoon({
  title,
  fase,
  text,
  children,
}: {
  title: string;
  fase: string;
  text: string;
  children?: ReactNode;
}) {
  return (
    <section className="card">
      <h2>{title}</h2>
      <p>{text}</p>
      <p>
        <span className="badge badge-progress">{fase}</span>
      </p>
      <p className="muted">
        Sin datos todavía: este módulo no está conectado a la base de
        datos.
      </p>
      {children}
    </section>
  );
}
