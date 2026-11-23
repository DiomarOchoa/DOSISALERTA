// Tarjetas de resumen de cumplimiento (Fase 8, Entrega 5).
// - Muestra los numeros del backend tal cual: nunca recalcula el
//   porcentaje ni promedia grupos.
// - compliance_percentage null -> "—", nunca 0 %.
// - Si hay canceladas, desglosa los motivos con conteo > 0; el
//   motivo desconocido (NULL) se muestra como tal.

import type { ComplianceSummary } from "../services/stats";
import { formatDateOnly } from "../utils/user";

const CANCEL_REASON_LABEL: Record<string, string> = {
  treatment_cancelled: "Tratamiento cancelado",
  treatment_paused: "Tratamiento pausado",
  treatment_completed: "Tratamiento completado",
  medication_deactivated: "Medicamento desactivado",
  link_removed: "Medicamento retirado del tratamiento",
  unknown: "Motivo desconocido",
};

function formatPercentage(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return `${value.toLocaleString("es-CO", { maximumFractionDigits: 1 })} %`;
}

// Ultimo dia incluido del periodo [from, to) del backend.
function addDays(dateStr: string, days: number): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!match) {
    return dateStr;
  }
  const date = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]) + days,
  );
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function StatsSummary({
  summary,
}: {
  summary: ComplianceSummary;
}) {
  const reasons = Object.entries(summary.cancelled_by_reason).filter(
    ([, count]) => count > 0,
  );

  return (
    <div>
      <p className="hint">
        Periodo: {formatDateOnly(summary.from)} –{" "}
        {formatDateOnly(addDays(summary.to, -1))}
      </p>
      <div className="stats-cards">
        <div className="stat-card stat-card-hero">
          <p className="stat-label">Cumplimiento</p>
          <p className="stat-value">
            {formatPercentage(summary.compliance_percentage)}
          </p>
        </div>
        <div className="stat-card">
          <p className="stat-label">Programadas</p>
          <p className="stat-value">{summary.scheduled}</p>
        </div>
        <div className="stat-card">
          <p className="stat-label">A tiempo</p>
          <p className="stat-value">{summary.taken_on_time}</p>
        </div>
        <div className="stat-card">
          <p className="stat-label">Tardías</p>
          <p className="stat-value">{summary.taken_late}</p>
        </div>
        <div className="stat-card">
          <p className="stat-label">Perdidas</p>
          <p className="stat-value">{summary.lost}</p>
        </div>
        <div className="stat-card">
          <p className="stat-label">Canceladas</p>
          <p className="stat-value">{summary.cancelled}</p>
        </div>
      </div>
      {summary.cancelled > 0 && reasons.length > 0 ? (
        <section className="card">
          <h3>Motivos de cancelación</h3>
          <ul className="reason-list">
            {reasons.map(([reason, count]) => (
              <li key={reason} className="reason-row">
                <span>{CANCEL_REASON_LABEL[reason] ?? reason}</span>
                <span>{count}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
