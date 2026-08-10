import { Suspense, lazy } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import { useRealtime } from "./hooks/useRealtime";
import Layout from "./components/Layout";
import Login from "./pages/Login";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const MediaPlayersPage = lazy(() => import("./pages/MediaPlayersPage"));
const SwitchesPage = lazy(() => import("./pages/SwitchesPage"));
const LogsPage = lazy(() => import("./pages/LogsPage"));
const CashRegistersPage = lazy(() => import("./pages/CashRegistersPage"));
const ComputersPage = lazy(() => import("./pages/ComputersPage"));
const NetworkSearchPage = lazy(() => import("./pages/NetworkSearchPage"));
const OneCPage = lazy(() => import("./pages/OneCPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const UsersPage = lazy(() => import("./pages/Users"));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage"));
const HonestSignPage = lazy(() => import("./pages/HonestSignPage"));
const CamerasPage = lazy(() => import("./pages/CamerasPage"));

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  useRealtime();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-[var(--brand)] border-t-transparent" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user?.is_superuser) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function RouteLoader() {
  return (
    <div className="flex h-[45vh] items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-[var(--brand)] border-t-transparent" />
    </div>
  );
}

function AnimatedRoutes() {
  const location = useLocation();
  return (
    <div key={location.pathname} className="h-full route-fade">
      <Suspense fallback={<RouteLoader />}>
        <Routes location={location}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/media-players" element={<MediaPlayersPage />} />
          <Route path="/switches" element={<SwitchesPage />} />
          <Route path="/cash-registers" element={<CashRegistersPage />} />
          <Route path="/honest-sign" element={<HonestSignPage />} />
          <Route path="/cameras" element={<CamerasPage />} />
          <Route path="/computers" element={<ComputersPage />} />
          <Route path="/network-search" element={<NetworkSearchPage />} />
          <Route path="/onec" element={<OneCPage />} />
          <Route path="/qr-generator" element={<Navigate to="/onec" replace />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route
            path="/users"
            element={
              <AdminRoute>
                <UsersPage />
              </AdminRoute>
            }
          />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <Layout>
              <AnimatedRoutes />
            </Layout>
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}
