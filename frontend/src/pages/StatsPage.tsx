import ModuleSoon from "../components/ModuleSoon";

// Marcador de la Entrega 0. Las estadisticas dependen de la Fase 7
// (stats_service + routers/stats.py); la pantalla esta prevista
// en la Entrega 5.
export default function StatsPage() {
  return (
    <ModuleSoon
      title="Estadísticas"
      fase="Entrega 5"
      text="Aquí verás tu porcentaje de cumplimiento y tus estadísticas de tomas. Llega con la Fase 7 (historial y estadísticas)."
    />
  );
}
