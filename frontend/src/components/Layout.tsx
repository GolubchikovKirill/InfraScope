import { useEffect, useRef, useState, type FocusEvent, type MouseEvent, type ReactNode } from "react";
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
  Cable,
  ShieldCheck,
  Camera,
  Tv,
  MonitorSmartphone,
  KeyRound,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { readThemeMode, setThemeMode, type ThemeMode } from "../theme";

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
    { match: (path) => path.startsWith("/screens"), title: "Экраны", subtitle: "Телевизоры в магазинах: кто включён и подключение" },
    { match: (path) => path.startsWith("/remote-access"), title: "Удалённый доступ", subtitle: "RustDesk как сервис: деплой, пароли, книга адресов, подключения" },
    { match: (path) => path.startsWith("/credentials"), title: "Пароли и учётные данные", subtitle: "Хранилище секретов инфраструктуры и генератор паролей" },
    { match: (path) => path.startsWith("/onec"), title: "QR-генерация", subtitle: "Файлы обмена и посадочные талоны" },
    { match: (path) => path.startsWith("/settings"), title: "Настройки", subtitle: "Параметры сети и приложения" },
    { match: (path) => path.startsWith("/logs"), title: "Логи", subtitle: "События доступности и операций" },
    { match: (path) => path.startsWith("/users"), title: "Пользователи", subtitle: "Доступы и роли" },
  ];
  const currentPage = pageTitles.find((item) => item.match(location.pathname)) ?? {
    title: "RegStaer-M InfraScope",
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
    { to: "/computers", label: "Компьютеры", icon: Laptop, visible: true },
    { to: "/screens", label: "Экраны", icon: Tv, visible: true },
  ];
  const baseItems = [
    { to: "/honest-sign", label: "Честный знак", icon: ShieldCheck, visible: true },
    { to: "/remote-access", label: "Удалённый доступ", icon: MonitorSmartphone, visible: true },
    { to: "/credentials", label: "Пароли", icon: KeyRound, visible: isSuperuser },
    { to: "/onec", label: "QR-генерация", icon: Cable, visible: true },
    { to: "/settings", label: "Настройки", icon: Settings2, visible: true },
    { to: "/logs", label: "Логи", icon: ScrollText, visible: true },
    { to: "/users", label: "Пользователи", icon: Users, visible: isSuperuser },
  ];
  const equipmentVisibleItems = equipmentItems.filter((item) => item.visible);
  const equipmentIsActive = equipmentVisibleItems.some((item) =>
    location.pathname.startsWith(item.to),
  );

  // The mobile chip strips scroll sideways; bring the current page's chip into
  // view, or on /computers the strip opened on "Принтеры" with the active
  // chip off-screen to the right.
  const mobileHeaderRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const active = mobileHeaderRef.current?.querySelector<HTMLElement>('[aria-current="page"]');
    active?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [location.pathname, isEquipmentOpen]);

  const handleToggleTheme = () => {
    const next: ThemeMode = themeMode === "light" ? "dark" : "light";
    setThemeMode(next);
    setThemeModeState(next);
  };

  const collapsed = !isSidebarVisible;
  // The rail has no labels, so hovering or tabbing onto an item names it. The
  // tip is fixed-positioned outside the nav: the nav scrolls, and a scroller
  // clips anything that pokes out past the rail's edge.
  const [railTip, setRailTip] = useState<{ label: string; top: number; left: number } | null>(null);
  const showRailTip = (label: string, el: HTMLElement) => {
    const rect = el.getBoundingClientRect();
    setRailTip({ label, top: rect.top + rect.height / 2, left: rect.right + 12 });
  };
  const hideRailTip = () => setRailTip(null);
  const railTipProps = (label: string) =>
    collapsed
      ? {
          "aria-label": label,
          onMouseEnter: (event: MouseEvent<HTMLElement>) => showRailTip(label, event.currentTarget),
          onFocus: (event: FocusEvent<HTMLElement>) => showRailTip(label, event.currentTarget),
          onMouseLeave: hideRailTip,
          onBlur: hideRailTip,
        }
      : {};
  const navItemClass = (isActive: boolean, nested = false) =>
    `inline-flex w-full items-center gap-3 whitespace-nowrap rounded-xl border text-sm font-medium transition ${
      collapsed ? "justify-center px-0 py-2.5" : `px-3 py-2.5 ${nested ? "pl-8" : ""}`
    } ${isActive ? "app-nav-active" : "app-nav-idle border-transparent"}`;

  const handleToggleSidebar = () => {
    setRailTip(null);
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
      {/* Collapsing used to remove the sidebar outright and float a
          "RegStaer-M" pill over the top-left corner, right on top of the page
          title. It now folds to an icon rail instead: navigation stays one
          click away and nothing overlaps the content. */}
      <aside
        className={`app-sidebar hidden md:flex md:flex-col md:sticky md:top-0 md:h-screen md:border-r shrink-0 overflow-hidden transition-[width] duration-200 ease-out ${
          collapsed ? "md:w-[4.5rem]" : "md:w-[17rem] lg:w-72"
        }`}
      >
        {collapsed ? (
          <div className="flex flex-col items-center gap-3 px-2 pt-5 pb-4 border-b border-[var(--sidebar-border)]">
            <span className="app-wordmark text-[1.6rem] text-white" aria-label="RegStaer-M">
              R<span className="app-wordmark-suffix">M</span>
            </span>
            <button
              type="button"
              onClick={handleToggleSidebar}
              className="app-rail-toggle"
              title="Развернуть меню"
              aria-label="Развернуть меню"
            >
              <PanelLeftOpen className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-start justify-between gap-2 px-6 pt-6 pb-5 border-b border-[var(--sidebar-border)]">
            <div className="flex flex-col items-start">
              <span className="app-wordmark text-[1.85rem] text-white">
                RegStaer<span className="app-wordmark-suffix">-M</span>
              </span>
              <span className="app-wordmark-product mt-2">InfraScope</span>
            </div>
            <button
              type="button"
              onClick={handleToggleSidebar}
              className="app-rail-toggle -mr-2"
              title="Свернуть меню"
              aria-label="Свернуть меню"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </div>
        )}

        <nav
          onScroll={hideRailTip}
          className={`flex-1 space-y-2 overflow-y-auto overflow-x-hidden app-compact-scroll ${collapsed ? "px-3 py-4" : "p-4"}`}
        >
          <NavLink to="/" end className={({ isActive }) => navItemClass(isActive)} {...railTipProps("Обзор")}>
            <LayoutDashboard className="h-4 w-4 shrink-0" />
            {!collapsed && "Обзор"}
          </NavLink>
          <button
            type="button"
            onClick={() => setEquipmentOpen((prev) => !prev)}
            className={`${navItemClass(equipmentIsActive)} ${collapsed ? "" : "justify-between"}`}
            aria-expanded={isEquipmentOpen}
            {...railTipProps("Оборудование")}
          >
            <span className="inline-flex items-center gap-3">
              <Server className="h-4 w-4 shrink-0" />
              {!collapsed && "Оборудование"}
            </span>
            {!collapsed && (isEquipmentOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />)}
          </button>
          {isEquipmentOpen && (
            // On the rail the indent is gone, so the group reads as a tray
            <div className={collapsed ? "app-rail-group space-y-1 p-1" : "space-y-2"}>
              {equipmentVisibleItems.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end
                  className={({ isActive }) => navItemClass(isActive, true)}
                  {...railTipProps(label)}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {!collapsed && label}
                </NavLink>
              ))}
            </div>
          )}
          {baseItems
            .filter((item) => item.visible)
            .map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} end className={({ isActive }) => navItemClass(isActive)} {...railTipProps(label)}>
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && label}
              </NavLink>
            ))}
        </nav>

        <div className={`border-t border-[var(--sidebar-border)] ${collapsed ? "px-3 py-4" : "p-4"}`}>
          <div className={`flex gap-2 ${collapsed ? "flex-col items-center" : "items-center"}`}>
            <button
              onClick={handleToggleTheme}
              className={`inline-flex items-center justify-center gap-1.5 rounded-lg border text-xs transition app-btn-secondary ${
                collapsed ? "h-9 w-9" : "px-2 py-1.5"
              }`}
              title={themeMode === "light" ? "Включить тёмную тему" : "Включить светлую тему"}
            >
              {themeMode === "light" ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
            </button>
            <button
              onClick={logout}
              className={`inline-flex items-center justify-center gap-1.5 rounded-lg border text-xs transition app-btn-secondary ${
                collapsed ? "h-9 w-9" : "flex-1 px-2 py-1.5"
              }`}
              title="Выйти из аккаунта"
              aria-label="Выход"
            >
              <LogOut className="h-3.5 w-3.5" />
              {!collapsed && "Выход"}
            </button>
          </div>
        </div>
      </aside>

      {railTip && (
        <div className="app-rail-tip" role="tooltip" style={{ top: railTip.top, left: railTip.left }}>
          {railTip.label}
        </div>
      )}

      <div className="flex-1 min-w-0 flex flex-col h-screen overflow-hidden relative">
        <header ref={mobileHeaderRef} className="app-header md:hidden sticky top-0 z-30 border-b backdrop-blur-xl">
          <div className="px-3 py-3 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="app-wordmark text-2xl text-[var(--brand)]">
                  RegStaer<span className="app-wordmark-suffix">-M</span>
                </span>
                <span className="app-wordmark-product">InfraScope</span>
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
            <nav className="app-scroll-x-hidden flex gap-2 overflow-x-auto">
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
                          : "app-nav-idle border-transparent text-slate-500 hover:border-slate-200 hover:bg-white/70"
                      }`
                    }
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {label}
                  </NavLink>
                ))}
            </nav>
            {isEquipmentOpen && (
              <nav className="app-scroll-x-hidden flex gap-2 overflow-x-auto">
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
                <h1 className="app-page-title truncate text-[1.75rem] leading-tight">{currentPage.title}</h1>
                <p className="app-page-subtitle truncate text-xs mt-0.5">{currentPage.subtitle}</p>
              </div>
              <div className="flex items-center gap-3">
                <div className="hidden md:flex flex-col items-end leading-tight">
                  <span className="app-account-name text-sm font-semibold">{displayName}</span>
                  <span className="app-account-subtitle text-xs">{buildAccountSubtitle(accountEmail, displayName, isSuperuser)}</span>
                </div>
                <div className="app-session-pill inline-flex items-center gap-2 rounded-full border border-[var(--app-panel-border)] bg-white/70 px-3 py-1.5 text-xs font-semibold">
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
