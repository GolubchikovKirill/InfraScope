import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import {
  ChevronDown,
  ChevronRight,
  LogOut,
  Server,
  LayoutDashboard,
  Printer,
  Users,
  Monitor,
  Laptop,
  Network,
  Moon,
  Sun,
  ScrollText,
  Settings2,
  Wallet,
  Radar,
  Cable,
  ShieldCheck,
  Camera,
} from "lucide-react";
import { readThemeMode, setThemeMode, type ThemeMode } from "../theme";
import { motion, AnimatePresence } from "framer-motion";

function buildAccountSubtitle(email: string, displayName: string, isSuperuser: boolean): string {
  if (email && displayName !== email) {
    return email;
  }
  return isSuperuser ? "Администратор" : "Пользователь";
}

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const isSuperuser = user?.is_superuser ?? false;
  const fullName = user?.full_name?.trim() ?? "";
  const displayName = fullName || user?.email || "Пользователь";
  const accountEmail = user?.email ?? "";
  const isOnline = Boolean(user);
  const pageTitles: Array<{ match: (path: string) => boolean; title: string; subtitle: string }> = [
    { match: (path) => path === "/", title: "Обзор инфраструктуры", subtitle: "Приоритеты, доступность и последние сигналы" },
    { match: (path) => path.startsWith("/printers"), title: "Принтеры", subtitle: "Статусы, тонер и склад картриджей" },
    { match: (path) => path.startsWith("/media-players"), title: "Медиаплееры", subtitle: "Управление воспроизведением и назначениями" },
    { match: (path) => path.startsWith("/switches"), title: "Сетевое оборудование", subtitle: "Свитчи, порты и точки доступа" },
    { match: (path) => path.startsWith("/cash-registers"), title: "Кассы", subtitle: "Доступность касс и учетные данные" },
    { match: (path) => path.startsWith("/honest-sign"), title: "Честный знак", subtitle: "Статус и удалённая инициализация Local Module" },
    { match: (path) => path.startsWith("/cameras"), title: "Камеры", subtitle: "Просмотр и перезагрузка камер по магазинам" },
    { match: (path) => path.startsWith("/computers"), title: "Компьютеры", subtitle: "Контроль доступности рабочих станций" },
    { match: (path) => path.startsWith("/network-search"), title: "Поиск в сети", subtitle: "Сканирование и сопоставление устройств" },
    { match: (path) => path.startsWith("/onec"), title: "QR-генерация", subtitle: "Файлы обмена и посадочные талоны" },
    { match: (path) => path.startsWith("/settings"), title: "Настройки", subtitle: "Параметры сети и приложения" },
    { match: (path) => path.startsWith("/logs"), title: "Логи", subtitle: "События доступности и операций" },
    { match: (path) => path.startsWith("/users"), title: "Пользователи", subtitle: "Доступы и роли" },
  ];
  const currentPage = pageTitles.find((item) => item.match(location.pathname)) ?? {
    title: "InfraScope",
    subtitle: "Панель управления инфраструктурой",
  };
  const [themeMode, setThemeModeState] = useState<ThemeMode>(() => readThemeMode());
  const [isSidebarVisible, setSidebarVisible] = useState<boolean>(() => {
    try {
      return localStorage.getItem("infrascope_sidebar_hidden") !== "1";
    } catch {
      return true;
    }
  });

  const [isEquipmentOpen, setEquipmentOpen] = useState(true);
  const equipmentItems = [
    { to: "/printers", label: "Принтеры", icon: Printer, visible: true },
    { to: "/media-players", label: "Медиаплееры", icon: Monitor, visible: true },
    { to: "/switches", label: "Сетевое оборудование", icon: Network, visible: true },
    { to: "/cameras", label: "Камеры", icon: Camera, visible: true },
    { to: "/cash-registers", label: "Кассы", icon: Wallet, visible: true },
    { to: "/honest-sign", label: "Честный знак", icon: ShieldCheck, visible: true },
    { to: "/computers", label: "Компьютеры", icon: Laptop, visible: true },
    { to: "/network-search", label: "Поиск в сети", icon: Radar, visible: true },
  ];
  const baseItems = [
    { to: "/onec", label: "QR-генерация", icon: Cable, visible: true },
    { to: "/settings", label: "Настройки", icon: Settings2, visible: true },
    { to: "/logs", label: "Логи", icon: ScrollText, visible: true },
    { to: "/users", label: "Пользователи", icon: Users, visible: isSuperuser },
  ];
  const equipmentVisibleItems = equipmentItems.filter((item) => item.visible);
  const equipmentIsActive = equipmentVisibleItems.some((item) =>
    location.pathname.startsWith(item.to),
  );

  const handleToggleTheme = () => {
    const next: ThemeMode = themeMode === "light" ? "dark" : "light";
    setThemeMode(next);
    setThemeModeState(next);
  };

  const handleToggleSidebar = () => {
    setSidebarVisible((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("infrascope_sidebar_hidden", next ? "0" : "1");
      } catch {
        // ignore storage errors
      }
      return next;
    });
  };

  return (
    <div className="min-h-screen app-shell md:flex">
      <aside className={`${isSidebarVisible ? "hidden md:flex" : "hidden"} app-sidebar md:w-[17rem] lg:w-72 md:flex-col md:sticky md:top-0 md:h-screen md:border-r`}>
        <div className="px-5 py-5 border-b border-[var(--app-panel-border)]">
          <div className="flex items-center gap-3 justify-between">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleToggleSidebar}
                className="app-logo-btn app-logo-live rounded-xl bg-linear-to-br from-[var(--brand-strong)] to-[var(--brand-bright)] p-2 shadow-md"
                title="Свернуть/развернуть меню"
              >
                <Server className="h-5 w-5 text-white" />
              </button>
              <div className="min-w-0">
                <div className="app-brand-title text-lg font-semibold">InfraScope</div>
                <div className="app-brand-subtitle text-xs">Панель инфраструктуры</div>
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-4 space-y-2 overflow-y-auto">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `inline-flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-medium transition ${
                isActive
                  ? "app-nav-active"
                  : "app-nav-idle border-transparent text-slate-500 hover:border-slate-200 hover:text-slate-700"
              }`
            }
          >
            <LayoutDashboard className="h-4 w-4 shrink-0" />
            Обзор
          </NavLink>
          <button
            type="button"
            onClick={() => setEquipmentOpen((prev) => !prev)}
            className={`inline-flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-sm font-medium transition ${
              equipmentIsActive ? "app-nav-active" : "app-nav-idle border-transparent text-slate-500 hover:border-slate-200 hover:text-slate-700"
            }`}
          >
            <span className="inline-flex items-center gap-3">
              <Server className="h-4 w-4 shrink-0" />
              Оборудование
            </span>
            {isEquipmentOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
          {isEquipmentOpen &&
            equipmentVisibleItems.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end
                className={({ isActive }) =>
                  `inline-flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 pl-8 text-sm font-medium transition ${
                    isActive
                      ? "app-nav-active"
                      : "app-nav-idle border-transparent text-slate-500 hover:border-slate-200 hover:text-slate-700"
                  }`
                }
              >
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </NavLink>
            ))}
          {baseItems
            .filter((item) => item.visible)
            .map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end
                className={({ isActive }) =>
                  `inline-flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-medium transition ${
                    isActive
                      ? "app-nav-active"
                      : "app-nav-idle border-transparent text-slate-500 hover:border-slate-200 hover:bg-white/60 hover:text-slate-700 dark:hover:bg-slate-800/60 dark:hover:text-slate-200"
                  }`
                }
              >
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </NavLink>
            ))}
        </nav>

        <div className="p-4 border-t border-[var(--app-panel-border)] space-y-2.5">
          <div className="flex items-center gap-2">
            <button
              onClick={handleToggleTheme}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg border px-2 py-1.5 text-xs transition app-btn-secondary"
              title={themeMode === "light" ? "Включить тёмную тему" : "Включить светлую тему"}
            >
              {themeMode === "light" ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
            </button>
            <button
              onClick={logout}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border px-2 py-1.5 text-xs transition app-btn-secondary"
              title="Выйти из аккаунта"
            >
              <LogOut className="h-3.5 w-3.5" />
              Выход
            </button>
          </div>
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col h-screen overflow-hidden relative">
        <AnimatePresence>
          {!isSidebarVisible && (
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              // z-40: was z-10, sitting UNDER .app-topbar's z-20 in the same
              // stacking context. They overlap in the top-left corner, so the
              // topbar was silently eating every click meant for this button
              // - the sidebar had no way back once hidden.
              className="hidden md:flex px-3 sm:px-5 lg:px-8 pt-3 absolute z-40"
            >
              <button
                type="button"
                onClick={handleToggleSidebar}
                className="inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs app-btn-secondary app-logo-live backdrop-blur-md bg-[var(--surface-1)]/85"
                title="Показать меню"
              >
                <Server className="h-4 w-4" />
                InfraScope
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        <header className="app-header md:hidden sticky top-0 z-30 border-b backdrop-blur-xl">
          <div className="px-3 py-3 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <div className="rounded-lg bg-linear-to-br from-[var(--brand-strong)] to-[var(--brand-bright)] p-1.5 shadow-sm">
                  <Server className="h-4 w-4 text-white" />
                </div>
                <span className="font-semibold text-slate-900 dark:text-slate-100">InfraScope</span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={handleToggleTheme}
                  className="inline-flex items-center rounded-lg border px-2 py-1.5 text-xs app-btn-secondary"
                >
                  {themeMode === "light" ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
                </button>
                <button
                  onClick={logout}
                  className="inline-flex items-center rounded-lg border px-2 py-1.5 text-xs app-btn-secondary"
                >
                  <LogOut className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
            <nav className="flex gap-2 overflow-x-auto pb-1">
              <button
                type="button"
                onClick={() => setEquipmentOpen((prev) => !prev)}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium whitespace-nowrap ${
                  equipmentIsActive ? "app-nav-active" : "app-nav-idle border-transparent text-slate-500 hover:border-slate-200"
                }`}
              >
                <Server className="h-3.5 w-3.5" />
                Оборудование
                {isEquipmentOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              </button>
              {baseItems
                .filter((item) => item.visible)
                .map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end
                    className={({ isActive }) =>
                      `inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium whitespace-nowrap ${
                        isActive
                          ? "app-nav-active"
                          : "app-nav-idle border-transparent text-slate-500 hover:border-slate-200 hover:bg-white/70 dark:hover:bg-slate-800/70"
                      }`
                    }
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {label}
                  </NavLink>
                ))}
            </nav>
            {isEquipmentOpen && (
              <nav className="flex gap-2 overflow-x-auto pb-1">
                {equipmentVisibleItems.map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end
                    className={({ isActive }) =>
                      `inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium whitespace-nowrap ${
                        isActive
                          ? "app-nav-active"
                          : "app-nav-idle border-transparent text-slate-500 hover:border-slate-200"
                      }`
                    }
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {label}
                  </NavLink>
                ))}
              </nav>
            )}
          </div>
        </header>

        <main className="flex-1 app-compact-scroll overflow-y-auto">
          <div className="app-topbar hidden md:block sticky top-0 z-20 border-b backdrop-blur-xl">
            <div className="app-main-frame mx-auto flex items-center justify-between gap-4 px-5 lg:px-7 py-4">
              <div className="min-w-0">
                <h1 className="app-page-title truncate text-xl font-semibold">{currentPage.title}</h1>
                <p className="app-page-subtitle truncate text-xs mt-0.5">{currentPage.subtitle}</p>
              </div>
              <div className="flex items-center gap-3">
                <div className="hidden md:flex flex-col items-end leading-tight">
                  <span className="app-account-name text-sm font-semibold">{displayName}</span>
                  <span className="app-account-subtitle text-xs">{buildAccountSubtitle(accountEmail, displayName, isSuperuser)}</span>
                </div>
                <div className="app-session-pill inline-flex items-center gap-2 rounded-full border border-[var(--app-panel-border)] bg-white/70 px-3 py-1.5 text-xs font-semibold dark:bg-slate-900/70">
                  <span className={`h-2 w-2 rounded-full ${isOnline ? "app-status-dot bg-emerald-500" : "bg-slate-400"}`} />
                  {isOnline ? "Сессия активна" : "Нет сессии"}
                </div>
              </div>
            </div>
          </div>
          <div className="app-main-frame mx-auto w-full px-2 sm:px-4 lg:px-7 py-5 sm:py-7">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
