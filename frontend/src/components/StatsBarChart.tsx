// Grafica de barras CSS (Fase 8, Entrega 5).
// - Sin librerias: cada barra mide el porcentaje de cumplimiento
//   del grupo, con el ancho en %.
// - Un grupo con scheduled=0 muestra "Sin dosis" (sin barra).
// - Un grupo con porcentaje null y scheduled>0 muestra "—".
// - El porcentaje es el del backend; nunca se recalcula ni se
//   promedia.

export interface ChartBar {
  key: string;
  label: string;
  percentage: number | null;
  scheduled: number;
}

function formatPercentage(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return `${value.toLocaleString("es-CO", { maximumFractionDigits: 1 })} %`;
}

export default function StatsBarChart({ bars }: { bars: ChartBar[] }) {
  return (
    <ul className="chart-list">
      {bars.map((bar) => (
        <li key={bar.key} className="chart-row">
          <div className="chart-head">
            <span className="chart-label">
              {bar.label}{" "}
              <span className="chart-sub">· {bar.scheduled} dosis</span>
            </span>
            <span
              className={
                bar.scheduled === 0 || bar.percentage === null
                  ? "chart-value chart-value-muted"
                  : "chart-value"
              }
            >
              {bar.scheduled === 0
                ? "Sin dosis"
                : formatPercentage(bar.percentage)}
            </span>
          </div>
          <div className="chart-track">
            {bar.percentage !== null ? (
              <span
                className="chart-bar"
                style={{ width: `${bar.percentage}%` }}
              />
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
