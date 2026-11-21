import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/Layout";
import DashboardPage from "./pages/DashboardPage";
import HistoryPage from "./pages/HistoryPage";
import StatsPage from "./pages/StatsPage";
import NotFoundPage from "./pages/NotFoundPage";

// Estructura de rutas de la Fase 8 (Entrega 0).
// Solo las paginas de la base: Inicio y los marcadores de
// Historial y Estadisticas (llegan en la Entrega 5).
// Sin autenticacion todavia: las rutas son abiertas.
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Navigate to="/inicio" replace />} />
          <Route path="/inicio" element={<DashboardPage />} />
          <Route path="/historial" element={<HistoryPage />} />
          <Route path="/estadisticas" element={<StatsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
