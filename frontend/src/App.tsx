import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import { AppLayout, PublicLayout } from "./components/Layout";
import LandingPage from "./pages/LandingPage";
import DashboardPage from "./pages/DashboardPage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import MedicationsPage from "./pages/MedicationsPage";
import MedicationCreatePage from "./pages/MedicationCreatePage";
import MedicationDetailPage from "./pages/MedicationDetailPage";
import TreatmentsPage from "./pages/TreatmentsPage";
import TreatmentCreatePage from "./pages/TreatmentCreatePage";
import TreatmentDetailPage from "./pages/TreatmentDetailPage";
import RemindersPage from "./pages/RemindersPage";
import HistoryPage from "./pages/HistoryPage";
import StatsPage from "./pages/StatsPage";
import CaregiversPage from "./pages/CaregiversPage";
import CalendarPage from "./pages/CalendarPage";
import ProfilePage from "./pages/ProfilePage";
import NotFoundPage from "./pages/NotFoundPage";

// Estructura de rutas de la Fase 8.
// La raiz (/) es la pagina publica de presentacion (landing).
// Las rutas publicas (/login, /registro) estan abiertas; todas las
// demas pasan por ProtectedRoute, que redirige a /login sin sesion.
// Todas las paginas estan implementadas (Entrega 5: historial y
// estadisticas); no quedan marcadores.
export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />

          <Route element={<PublicLayout />}>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/registro" element={<RegisterPage />} />
          </Route>

          <Route element={<ProtectedRoute />}>
            <Route element={<AppLayout />}>
              <Route path="/inicio" element={<DashboardPage />} />
              <Route path="/medicamentos" element={<MedicationsPage />} />
              <Route
                path="/medicamentos/nuevo"
                element={<MedicationCreatePage />}
              />
              <Route
                path="/medicamentos/:id"
                element={<MedicationDetailPage />}
              />
              <Route path="/tratamientos" element={<TreatmentsPage />} />
              <Route
                path="/tratamientos/nuevo"
                element={<TreatmentCreatePage />}
              />
              <Route
                path="/tratamientos/:id"
                element={<TreatmentDetailPage />}
              />
              <Route path="/recordatorios" element={<RemindersPage />} />
              <Route path="/historial" element={<HistoryPage />} />
              <Route path="/estadisticas" element={<StatsPage />} />
              <Route path="/cuidadores" element={<CaregiversPage />} />
              <Route path="/calendario" element={<CalendarPage />} />
              <Route path="/perfil" element={<ProfilePage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
