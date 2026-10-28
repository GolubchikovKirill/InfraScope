import { Suspense, lazy, useEffect } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import { useRealtime } from "./hooks/useRealtime";
import Layout from "./components/Layout";
import Login from "./pages/Login";

const pageLoaders = {
  Dashboard: () => import("./pages/Dashboard"),
  OverviewPage: () => import("./pages/OverviewPage"),
  MediaPlayersPage: () => import("./pages/MediaPlayersPage"),
  SwitchesPage: () => import("./pages/SwitchesPage"),
  LogsPage: () => import("./pages/LogsPage"),
  CashRegistersPage: () => import("./pages/CashRegistersPage"),
  ComputersPage: () => import("./pages/ComputersPage"),
  OneCPage: () => import("./pages/OneCPage"),
  SettingsPage: () => import("./pages/SettingsPage"),
  UsersPage: () => import("./pages/Users"),
  NotFoundPage: () => import("./pages/NotFoundPage"),
  HonestSignPage: () => import("./pages/HonestSignPage"),
  ScreensPage: () => import("./pages/ScreensPage"),
  CamerasPage: () => import("./pages/CamerasPage"),
  RemoteAccessPage: () => import("./pages/RemoteAccessPage"),
  CredentialsPage: () => import("./pages/CredentialsPage"),
};

const Dashboard = lazy(pageLoaders.Dashboard);
const OverviewPage = lazy(pageLoaders.OverviewPage);
const MediaPlayersPage = lazy(pageLoaders.MediaPlayersPage);
const SwitchesPage = lazy(pageLoaders.SwitchesPage);
const LogsPage = lazy(pageLoaders.LogsPage);
const CashRegistersPage = lazy(pageLoaders.CashRegistersPage);
const ComputersPage = lazy(pageLoaders.ComputersPage);
const OneCPage = lazy(pageLoaders.OneCPage);
const SettingsPage = lazy(pageLoaders.SettingsPage);
const UsersPage = lazy(pageLoaders.UsersPage);
const NotFoundPage = lazy(pageLoaders.NotFoundPage);
const HonestSignPage = lazy(pageLoaders.HonestSignPage);
const ScreensPage = lazy(pageLoaders.ScreensPage);
const CamerasPage = lazy(pageLoaders.CamerasPage);
const RemoteAccessPage = lazy(pageLoaders.RemoteAccessPage);
const CredentialsPage = lazy(pageLoaders.CredentialsPage);

/**
 * Fetch every page's chunk once the browser is idle after sign-in, so the first
 * visit to a section renders at once instead of showing the route spinner while
 * its chunk downloads. Pages are code-split for the first paint, not to be
 * fetched on click; together they are a few hundred kB, gzip far less.
 */
function usePrefetchPages(enabled: boolean) {
  useEffect(() => {
    // jsdom (unit tests) would import every page module in the background
    if (!enabled || navigator.userAgent.includes("jsdom")) return;
    const prefetch = () => {
      for (const load of Object.values(pageLoaders)) void load().catch(() => undefined);
    };
    if (typeof window.requestIdleCallback === "function") {
      const handle = window.requestIdleCallback(prefetch, { timeout: 4000 });
      return () => window.cancelIdleCallback(handle);
    }
    const timer = globalThis.setTimeout(prefetch, 1500);
    return () => globalThis.clearTimeout(timer);
  }, [enabled]);
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  useRealtime();
  usePrefetchPages(Boolean(user));

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
          <Route path="/" element={<OverviewPage />} />
          <Route path="/printers" element={<Dashboard />} />
          <Route path="/media-players" element={<MediaPlayersPage />} />
          <Route path="/switches" element={<SwitchesPage />} />
          <Route path="/cash-registers" element={<CashRegistersPage />} />
          <Route path="/honest-sign" element={<HonestSignPage />} />
          <Route path="/screens" element={<ScreensPage />} />
          <Route path="/cameras" element={<CamerasPage />} />
          <Route path="/computers" element={<ComputersPage />} />
          <Route path="/remote-access" element={<RemoteAccessPage />} />
          <Route
            path="/credentials"
            element={
              <AdminRoute>
                <CredentialsPage />
              </AdminRoute>
            }
          />
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
