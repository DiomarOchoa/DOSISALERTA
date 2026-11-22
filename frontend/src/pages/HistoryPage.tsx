import ModuleSoon from "../components/ModuleSoon";

// Marcador de la Entrega 0. El historial depende de la Fase 7
// (stats_service + routers/stats.py); la pantalla esta prevista
// en la Entrega 5.
export default function HistoryPage() {
  return (
    <ModuleSoon
      title="Historial"
      fase="Entrega 5"
      text="Aquí verás el historial de dosis tomadas, pospuestas y perdidas. Llega con la Fase 7 (historial y estadísticas)."
    />
  );
}
