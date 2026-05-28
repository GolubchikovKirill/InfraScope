import { Suspense, lazy } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import { useRealtime } from "./hooks/useRealtime";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import { AnimatePresence, motion } from "framer-motion";

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

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  useRealtime();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-rose-500 border-t-transparent" />
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
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-rose-500 border-t-transparent" />
    </div>
  );
}

function AnimatedRoutes() {
  const location = useLocation();
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={location.pathname}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.2 }}
        className="h-full"
      >
        <Suspense fallback={<RouteLoader />}>
          <Routes location={location}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/media-players" element={<MediaPlayersPage />} />
            <Route path="/switches" element={<SwitchesPage />} />
            <Route path="/cash-registers" element={<CashRegistersPage />} />
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
      </motion.div>
    </AnimatePresence>
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
