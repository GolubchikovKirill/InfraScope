import { useMemo, type ReactNode } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Boxes,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Laptop,
  Monitor,
  Network,
  Printer,
  ReceiptText,
  RefreshCw,
  ShieldAlert,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  getCartridgeStocks,
  getCashRegisters,
  getComputers,
  getEventLogs,
  getMediaPlayers,
  getPrinters,
  getSwitches,
  type EventLog,
} from "../client";

type HealthTone = "ok" | "warning" | "danger" | "neutral";

type FleetSection = {
  id: string;
  label: string;
  offlineForms: [string, string, string];
  to: string;
  icon: LucideIcon;
  total: number;
  online: number;
  offline: number;
  unknown: number;
};

type Priority = {
  id: string;
  title: string;
  detail: string;
  to: string;
  tone: Exclude<HealthTone, "neutral">;
  icon: LucideIcon;
};

const HEALTH_TONE_CLASSES: Record<HealthTone, { icon: string; badge: string; count: string }> = {
  ok: {
    icon: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
    badge: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300",
    count: "text-emerald-700 dark:text-emerald-300",
  },
  warning: {
    icon: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
    badge: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300",
    count: "text-amber-700 dark:text-amber-300",
  },
  danger: {
    icon: "bg-[var(--danger-bg)] text-[var(--danger-fg)]",
    badge: "border-[var(--danger-border)] bg-[var(--danger-bg)] text-[var(--danger-fg)]",
    count: "text-[var(--danger-fg)]",
  },
  neutral: {
    icon: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    badge: "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300",
    count: "text-slate-700 dark:text-slate-200",
  },
};

function statusCounts(rows: Array<{ is_online: boolean | null }>) {
  return rows.reduce(
    (counts, row) => {
      if (row.is_online === true) counts.online += 1;
      else if (row.is_online === false) counts.offline += 1;
      else counts.unknown += 1;
      return counts;
    },
    { online: 0, offline: 0, unknown: 0 },
  );
}

function formatUpdatedAt(value: number): string {
  if (!value) return "ожидание данных";
  return new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" }).format(value);
}

function formatEventTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" }).format(date);
}

function eventTone(event: EventLog): HealthTone {
  if (event.severity === "critical" || event.severity === "error") return "danger";
  if (event.severity === "warning") return "warning";
  return "neutral";
}

function eventLabel(event: EventLog): string {
  if (event.severity === "critical") return "Критично";
  if (event.severity === "error") return "Ошибка";
  if (event.severity === "warning") return "Внимание";
  return "Событие";
}

function fleetTone(section: FleetSection): HealthTone {
  if (section.offline > 0) return "danger";
  if (section.unknown > 0) return "warning";
  return "ok";
}

function pluralRu(value: number, [one, few, many]: [string, string, string]): string {
  const lastTwo = value % 100;
  const last = value % 10;
  if (lastTwo >= 11 && lastTwo <= 14) return many;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

function CashRegisterAttention({ count }: { count: number }) {
  if (!count) return null;
  return <span className="text-xs text-amber-700 dark:text-amber-300">+ {count} требуют проверки</span>;
}

export default function OverviewPage() {
  const queryOptions = { staleTime: 30_000, refetchInterval: 60_000, placeholderData: keepPreviousData };
  const laserPrintersQuery = useQuery({
    queryKey: ["printers", "laser", undefined],
    queryFn: () => getPrinters(undefined, "laser"),
    ...queryOptions,
  });
  const labelPrintersQuery = useQuery({
    queryKey: ["printers", "label", undefined],
    queryFn: () => getPrinters(undefined, "label"),
    ...queryOptions,
  });
  const switchesQuery = useQuery({ queryKey: ["switches", undefined], queryFn: () => getSwitches(), ...queryOptions });
  const cashRegistersQuery = useQuery({ queryKey: ["cash-registers", undefined], queryFn: () => getCashRegisters(), ...queryOptions });
  const computersQuery = useQuery({ queryKey: ["computers", undefined], queryFn: () => getComputers(), ...queryOptions });
  const mediaPlayersQuery = useQuery({ queryKey: ["media-players", undefined, undefined], queryFn: () => getMediaPlayers(), ...queryOptions });
  const cartridgesQuery = useQuery({ queryKey: ["cartridge-stock", undefined], queryFn: () => getCartridgeStocks(), ...queryOptions });
  const logsQuery = useQuery({ queryKey: ["logs", "overview"], queryFn: () => getEventLogs({ limit: 40 }), ...queryOptions });

  const laserPrinters = laserPrintersQuery.data?.data ?? [];
  const labelPrinters = labelPrintersQuery.data?.data ?? [];
  const switches = switchesQuery.data?.data ?? [];
  const cashRegisters = cashRegistersQuery.data?.data ?? [];
  const computers = computersQuery.data?.data ?? [];
  const mediaPlayers = mediaPlayersQuery.data?.data ?? [];
  const cartridgeStocks = cartridgesQuery.data?.data ?? [];
  const events = logsQuery.data?.data ?? [];

  const printerRows = [...laserPrinters, ...labelPrinters];
  const printerCounts = statusCounts(printerRows);
  const switchCounts = statusCounts(switches);
  const cashRegisterCounts = statusCounts(cashRegisters);
  const computerCounts = statusCounts(computers);
  const mediaPlayerCounts = statusCounts(mediaPlayers);

  const fleets: FleetSection[] = [
    { id: "switches", label: "Сеть", offlineForms: ["свитч", "свитча", "свитчей"], to: "/switches", icon: Network, total: switches.length, ...switchCounts },
    { id: "cash-registers", label: "Кассы", offlineForms: ["касса", "кассы", "касс"], to: "/cash-registers", icon: ReceiptText, total: cashRegisters.length, ...cashRegisterCounts },
    { id: "printers", label: "Печать", offlineForms: ["принтер", "принтера", "принтеров"], to: "/printers", icon: Printer, total: printerRows.length, ...printerCounts },
    { id: "media", label: "Медиаплееры", offlineForms: ["медиаплеер", "медиаплеера", "медиаплееров"], to: "/media-players", icon: Monitor, total: mediaPlayers.length, ...mediaPlayerCounts },
    { id: "computers", label: "Компьютеры", offlineForms: ["компьютер", "компьютера", "компьютеров"], to: "/computers", icon: Laptop, total: computers.length, ...computerCounts },
  ];

  const lowTonerCount = laserPrinters.filter((printer) =>
    [printer.toner_black, printer.toner_cyan, printer.toner_magenta, printer.toner_yellow].some(
      (level) => level !== null && level >= 0 && level <= 15,
    ),
  ).length;
  const lowStockCount = cartridgeStocks.filter((stock) => stock.minimum_stock > 0 && stock.quantity_on_hand <= stock.minimum_stock).length;
  const cashRegisterAttentionCount = cashRegisters.filter((cashRegister) => {
    const piot = (cashRegister.piot_status ?? "").trim().toLocaleUpperCase("ru-RU");
    const drawer = (cashRegister.cash_drawer ?? "").trim().toLocaleLowerCase("ru-RU");
    const piotProblem = Boolean(piot) && (piot.includes("НЕ ОБНОВЛЕН") || !piot.includes("ОБНОВЛЕН"));
    const drawerProblem = Boolean(drawer) && drawer !== "да";
    return Boolean(cashRegister.terminal_status?.trim() || piotProblem || drawerProblem);
  }).length;
  const recentIncidents = events.filter((event) => event.severity !== "info").slice(0, 6);
  const errorEventCount = events.filter((event) => event.severity === "critical" || event.severity === "error").length;
  const totalOnline = fleets.reduce((total, fleet) => total + fleet.online, 0);
  const totalOffline = fleets.reduce((total, fleet) => total + fleet.offline, 0);
  const totalUnknown = fleets.reduce((total, fleet) => total + fleet.unknown, 0);
  const totalMonitored = fleets.reduce((total, fleet) => total + fleet.total, 0);
  const healthBase = totalOnline + totalOffline;
  const healthPercent = healthBase ? Math.round((totalOnline / healthBase) * 100) : 0;
  const attentionCount = totalOffline + totalUnknown + lowTonerCount + lowStockCount + cashRegisterAttentionCount + errorEventCount;
  const priorities = useMemo<Priority[]>(() => {
    const result: Priority[] = [];
    for (const fleet of fleets) {
      if (!fleet.offline) continue;
      result.push({
        id: `${fleet.id}-offline`,
        title: `Недоступно: ${fleet.offline} ${pluralRu(fleet.offline, fleet.offlineForms)}`,
        detail: `${fleet.label}: ${fleet.offline} из ${fleet.total} не отвечают на последний опрос`,
        to: fleet.to,
        tone: "danger",
        icon: TriangleAlert,
      });
    }
    if (cashRegisterAttentionCount) {
      result.push({ id: "cash-attention", title: "Кассы требуют проверки", detail: `${cashRegisterAttentionCount} с проблемой терминала, ПИОТ или денежного ящика`, to: "/cash-registers", tone: "warning", icon: ReceiptText });
    }
    if (lowTonerCount) {
      result.push({ id: "toner", title: "Низкий уровень тонера", detail: `${lowTonerCount} принтеров с уровнем расходника 15% или ниже`, to: "/printers", tone: "warning", icon: Printer });
    }
    if (lowStockCount) {
      result.push({ id: "stock", title: "Нужно пополнить склад", detail: `${lowStockCount} позиций на минимальном остатке или ниже`, to: "/printers", tone: "warning", icon: Boxes });
    }
    if (totalUnknown) {
      result.push({ id: "unknown", title: "Нет свежего статуса", detail: `${totalUnknown} устройств ещё не имеют результата опроса`, to: "/logs", tone: "warning", icon: Clock3 });
    }
    return result.slice(0, 6);
  }, [cashRegisterAttentionCount, fleets, lowStockCount, lowTonerCount, totalUnknown]);

  const dataUpdatedAt = Math.max(
    laserPrintersQuery.dataUpdatedAt,
    labelPrintersQuery.dataUpdatedAt,
    switchesQuery.dataUpdatedAt,
    cashRegistersQuery.dataUpdatedAt,
    computersQuery.dataUpdatedAt,
    mediaPlayersQuery.dataUpdatedAt,
    cartridgesQuery.dataUpdatedAt,
    logsQuery.dataUpdatedAt,
  );
  const isLoading = [laserPrintersQuery, labelPrintersQuery, switchesQuery, cashRegistersQuery, computersQuery, mediaPlayersQuery]
    .some((query) => query.isLoading);
  const hasLoadError = [laserPrintersQuery, labelPrintersQuery, switchesQuery, cashRegistersQuery, computersQuery, mediaPlayersQuery, cartridgesQuery, logsQuery]
    .some((query) => query.isError);
  const isHealthy = !isLoading && attentionCount === 0;

  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-2xl border border-[var(--app-panel-border)] bg-[radial-gradient(circle_at_top_right,_rgba(37,99,235,0.18),_transparent_38%),linear-gradient(135deg,var(--app-panel-bg),color-mix(in_srgb,var(--app-panel-bg)_86%,var(--brand-soft)))] p-5 shadow-sm sm:p-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-2xl">
            <div className={`mb-3 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${isHealthy ? HEALTH_TONE_CLASSES.ok.badge : attentionCount ? HEALTH_TONE_CLASSES.warning.badge : HEALTH_TONE_CLASSES.neutral.badge}`}>
              {isHealthy ? <CheckCircle2 className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
              {isLoading ? "Собираем сводку" : isHealthy ? "Инфраструктура в норме" : "Есть задачи, требующие внимания"}
            </div>
            <h2 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100 sm:text-3xl">Здоровье инфраструктуры</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">Сначала — то, что влияет на работу магазинов. Ниже — состояние всей подключённой техники без запуска дополнительных опросов.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/logs" className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm"><ReceiptText className="h-4 w-4" />Логи</Link>
            <button type="button" onClick={() => void Promise.all([laserPrintersQuery.refetch(), labelPrintersQuery.refetch(), switchesQuery.refetch(), cashRegistersQuery.refetch(), computersQuery.refetch(), mediaPlayersQuery.refetch(), cartridgesQuery.refetch(), logsQuery.refetch()])} className="app-btn-primary inline-flex items-center gap-2 px-3 py-2 text-sm">
              <RefreshCw className="h-4 w-4" />Обновить сводку
            </button>
          </div>
        </div>
        <div className="mt-5 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400"><Clock3 className="h-3.5 w-3.5" />Данные обновлены: {formatUpdatedAt(dataUpdatedAt)}. Фактический опрос устройств выполняется по расписанию на сервере.</div>
      </section>

      {hasLoadError && <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />Часть данных сейчас недоступна. Показаны последние сохранённые результаты; попробуйте обновить сводку позже.</div>}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Доступность" value={healthBase ? `${healthPercent}%` : "—"} detail={healthBase ? `${totalOnline} из ${healthBase} отвечают` : "нет результатов опроса"} tone={totalOffline ? "danger" : totalUnknown ? "warning" : "ok"} />
        <Metric label="Недоступны" value={totalOffline} detail={totalOffline ? "нужно проверить связь" : "нет недоступных устройств"} tone={totalOffline ? "danger" : "ok"} />
        <Metric label="Внимание" value={attentionCount} detail="устройства, расходники и ошибки" tone={attentionCount ? "warning" : "ok"} />
        <Metric label="Под контролем" value={totalMonitored} detail={totalUnknown ? `${totalUnknown} без статуса` : "все категории имеют статус"} tone={totalUnknown ? "warning" : "neutral"} />
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(20rem,0.75fr)]">
        <div className="app-panel overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-[var(--app-panel-border)] px-5 py-4">
            <div><h3 className="font-semibold text-slate-900 dark:text-slate-100">Приоритеты сейчас</h3><p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Только то, что требует действия или проверки.</p></div>
            {priorities.length > 0 && <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${HEALTH_TONE_CLASSES.warning.badge}`}>{priorities.length}</span>}
          </div>
          {isLoading ? <PrioritySkeleton /> : priorities.length ? <div className="divide-y divide-[var(--app-panel-border)]">{priorities.map((priority) => <PriorityRow key={priority.id} priority={priority} />)}</div> : <div className="flex min-h-48 flex-col items-center justify-center px-5 py-8 text-center"><div className={`mb-3 rounded-xl p-3 ${HEALTH_TONE_CLASSES.ok.icon}`}><CheckCircle2 className="h-6 w-6" /></div><p className="font-medium text-slate-800 dark:text-slate-100">Срочных задач нет</p><p className="mt-1 max-w-sm text-sm text-slate-500 dark:text-slate-400">Устройства отвечают, расходники не на минимуме, а в свежих данных нет ошибок.</p></div>}
        </div>

        <div className="app-panel overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-[var(--app-panel-border)] px-5 py-4"><div><h3 className="font-semibold text-slate-900 dark:text-slate-100">Последние сигналы</h3><p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Ошибки и предупреждения из журнала.</p></div><Link to="/logs" className="text-xs font-semibold text-[var(--brand)] hover:text-[var(--brand-strong)]">Все логи</Link></div>
          {recentIncidents.length ? <div className="divide-y divide-[var(--app-panel-border)]">{recentIncidents.map((event) => <EventRow key={event.id} event={event} />)}</div> : <div className="flex min-h-48 flex-col items-center justify-center px-5 py-8 text-center text-sm text-slate-500 dark:text-slate-400"><CheckCircle2 className="mb-2 h-6 w-6 text-emerald-500" />В последних событиях нет предупреждений и ошибок.</div>}
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-end justify-between gap-4"><div><h3 className="font-semibold text-slate-900 dark:text-slate-100">По категориям</h3><p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">Откройте нужный раздел — проблемные устройства в нём уже находятся первыми.</p></div></div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{fleets.map((fleet) => <FleetCard key={fleet.id} fleet={fleet} extra={fleet.id === "cash-registers" ? <CashRegisterAttention count={cashRegisterAttentionCount} /> : undefined} />)}</div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <StockSummary label="Расходники" value={lowTonerCount} description="принтеров с тонером ≤ 15%" to="/printers" icon={Printer} tone={lowTonerCount ? "warning" : "ok"} />
        <StockSummary label="Склад картриджей" value={lowStockCount} description="позиций на минимальном остатке или ниже" to="/printers" icon={Boxes} tone={lowStockCount ? "warning" : "ok"} />
      </section>
    </div>
  );
}

function Metric({ label, value, detail, tone }: { label: string; value: string | number; detail: string; tone: HealthTone }) {
  return <div className="app-panel p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p><p className={`mt-1 text-2xl font-semibold tracking-tight ${HEALTH_TONE_CLASSES[tone].count}`}>{value}</p></div><div className={`rounded-xl p-2 ${HEALTH_TONE_CLASSES[tone].icon}`}>{tone === "ok" ? <CheckCircle2 className="h-4 w-4" /> : tone === "danger" ? <TriangleAlert className="h-4 w-4" /> : <CircleAlert className="h-4 w-4" />}</div></div><p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{detail}</p></div>;
}

function PrioritySkeleton() {
  return <div className="space-y-3 p-5">{Array.from({ length: 3 }).map((_, index) => <div key={index} className="flex gap-3"><div className="app-skeleton h-10 w-10 shrink-0" /><div className="flex-1 space-y-2"><div className="app-skeleton h-4 w-2/3" /><div className="app-skeleton h-3 w-full" /></div></div>)}</div>;
}

function PriorityRow({ priority }: { priority: Priority }) {
  const Icon = priority.icon;
  return <Link to={priority.to} className="group flex items-center gap-3 px-5 py-4 transition hover:bg-slate-50 dark:hover:bg-slate-800/50"><div className={`rounded-xl p-2.5 ${HEALTH_TONE_CLASSES[priority.tone].icon}`}><Icon className="h-4 w-4" /></div><div className="min-w-0 flex-1"><p className="font-medium text-slate-800 dark:text-slate-100">{priority.title}</p><p className="mt-0.5 truncate text-sm text-slate-500 dark:text-slate-400">{priority.detail}</p></div><ArrowRight className="h-4 w-4 shrink-0 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-[var(--brand)]" /></Link>;
}

function EventRow({ event }: { event: EventLog }) {
  const tone = eventTone(event);
  return <Link to="/logs" className="group flex items-start gap-3 px-5 py-3.5 transition hover:bg-slate-50 dark:hover:bg-slate-800/50"><div className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${tone === "danger" ? "bg-red-500" : "bg-amber-500"}`} /><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${HEALTH_TONE_CLASSES[tone].badge}`}>{eventLabel(event)}</span><span className="truncate text-xs text-slate-500 dark:text-slate-400">{event.device_name ?? event.category}</span></div><p className="mt-1 line-clamp-2 text-sm text-slate-700 dark:text-slate-200">{event.message}</p></div><span className="shrink-0 text-[11px] text-slate-400">{formatEventTime(event.created_at)}</span></Link>;
}

function FleetCard({ fleet, extra }: { fleet: FleetSection; extra?: ReactNode }) {
  const tone = fleetTone(fleet);
  const Icon = fleet.icon;
  return <Link to={fleet.to} className="app-panel group block p-4 transition hover:-translate-y-0.5 hover:shadow-md"><div className="flex items-start justify-between gap-3"><div className={`rounded-xl p-2.5 ${HEALTH_TONE_CLASSES[tone].icon}`}><Icon className="h-5 w-5" /></div><ArrowRight className="h-4 w-4 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-[var(--brand)]" /></div><p className="mt-4 font-semibold text-slate-800 dark:text-slate-100">{fleet.label}</p><div className="mt-2 flex items-baseline gap-1"><span className={`text-2xl font-semibold ${HEALTH_TONE_CLASSES[tone].count}`}>{fleet.offline || fleet.unknown || fleet.online}</span><span className="text-xs text-slate-500 dark:text-slate-400">из {fleet.total}</span></div><div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs"><span className="text-emerald-700 dark:text-emerald-300">Онлайн {fleet.online}</span>{fleet.offline > 0 && <span className="text-[var(--danger-fg)]">Оффлайн {fleet.offline}</span>}{fleet.unknown > 0 && <span className="text-amber-700 dark:text-amber-300">Нет статуса {fleet.unknown}</span>}</div>{extra && <div className="mt-2">{extra}</div>}</Link>;
}

function StockSummary({ label, value, description, to, icon: Icon, tone }: { label: string; value: number; description: string; to: string; icon: LucideIcon; tone: HealthTone }) {
  return <Link to={to} className="app-panel group flex items-center gap-4 p-4 transition hover:-translate-y-0.5 hover:shadow-md"><div className={`rounded-xl p-3 ${HEALTH_TONE_CLASSES[tone].icon}`}><Icon className="h-5 w-5" /></div><div className="min-w-0 flex-1"><p className="font-medium text-slate-800 dark:text-slate-100">{label}</p><p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{value ? `${value} ${description}` : "запас в пределах нормы"}</p></div><ArrowRight className="h-4 w-4 shrink-0 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-[var(--brand)]" /></Link>;
}
