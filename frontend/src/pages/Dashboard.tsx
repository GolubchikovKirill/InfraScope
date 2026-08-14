import { useMemo, useState } from "react";
import { keepPreviousData, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Plus, Search, Printer as PrinterIcon, Tag, Check, Archive } from "lucide-react";
import {
  getCartridgeStockMovements,
  getCartridgeStocks,
  getPrinters,
  getOfflineRiskPredictions,
  issueCartridgeStock,
  pollAllPrinters,
  pollPrinter,
  createPrinter,
  updatePrinter,
  updateCartridgeStock,
  deletePrinter,
  getTonerPredictions,
  type MLOfflineRiskPrediction,
  type MLTonerPrediction,
  type Printer,
  type PrinterType,
} from "../client";
import { useAuth } from "../auth";
import PrinterCard from "../components/PrinterCard";
import ZebraCard from "../components/ZebraCard";
import { useEntityAutoPoll } from "../hooks/useEntityAutoPoll";
import PrinterForm from "../components/PrinterForm";
import CartridgeStockPanel from "../components/CartridgeStockPanel";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useConfirm } from "../components/ConfirmDialog";
import PathSuspectBanner from "../components/PathSuspectBanner";

type TabKey = PrinterType | "cartridges";
type StatusFilter = "all" | "online" | "offline" | "low_toner";

const TABS: { key: TabKey; label: string; icon: typeof PrinterIcon }[] = [
  { key: "laser", label: "Картриджные", icon: PrinterIcon },
  { key: "label", label: "Этикеточные", icon: Tag },
  { key: "cartridges", label: "Склад картриджей", icon: Archive },
];

export default function Dashboard() {
  const { user } = useAuth();
  const isSuperuser = user?.is_superuser ?? false;
  const queryClient = useQueryClient();
  const confirm = useConfirm();

  const [activeTab, setActiveTab] = useState<TabKey>("laser");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editingPrinter, setEditingPrinter] = useState<Printer | null>(null);
  const [pollingIds, setPollingIds] = useState<Set<string>>(new Set());
  const [formError, setFormError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const printerTab: PrinterType = activeTab === "label" ? "label" : "laser";
  const debouncedSearch = useDebouncedValue(search, 300);
  const [selectedStockId, setSelectedStockId] = useState<string | null>(null);
  const [savingStockId, setSavingStockId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["printers", printerTab, debouncedSearch],
    queryFn: () => getPrinters(debouncedSearch || undefined, printerTab),
    enabled: activeTab !== "cartridges",
    placeholderData: keepPreviousData,
  });
  const { data: cartridgeStockData, isLoading: isStockLoading } = useQuery({
    queryKey: ["cartridge-stock", debouncedSearch],
    queryFn: () => getCartridgeStocks(debouncedSearch || undefined),
    enabled: activeTab === "cartridges",
    placeholderData: keepPreviousData,
  });
  const { data: selectedMovementsData } = useQuery({
    queryKey: ["cartridge-stock", selectedStockId, "movements"],
    queryFn: () => getCartridgeStockMovements(selectedStockId!),
    enabled: activeTab === "cartridges" && Boolean(selectedStockId),
  });
  const { data: tonerPredictionsData } = useQuery({
    queryKey: ["ml-toner-predictions"],
    queryFn: () => getTonerPredictions(),
    enabled: printerTab === "laser",
    refetchInterval: 60_000,
  });
  const { data: riskPredictionsData } = useQuery({
    queryKey: ["ml-offline-risk-printer"],
    queryFn: () => getOfflineRiskPredictions("printer"),
    refetchInterval: 60_000,
  });

  const pollAllMut = useMutation({
    mutationFn: () => pollAllPrinters(printerTab),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["printers"] }),
  });

  const updateStockMut = useMutation({
    mutationFn: ({ id, quantity, minimum }: { id: string; quantity: number; minimum: number }) =>
      updateCartridgeStock(id, { quantity_on_hand: quantity, minimum_stock: minimum }),
    onMutate: ({ id }) => setSavingStockId(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cartridge-stock"] }),
    onSettled: () => setSavingStockId(null),
  });

  const issueStockMut = useMutation({
    mutationFn: (id: string) => issueCartridgeStock(id, { quantity: 1 }),
    onMutate: (id) => setSavingStockId(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cartridge-stock"] }),
    onSettled: () => setSavingStockId(null),
  });

  // Real device polling now runs on a schedule in the backend (Celery Beat),
  // so this no longer triggers a real poll from every open tab - it just
  // refreshes from cache. Realtime updates arrive via WebSocket regardless.
  useEntityAutoPoll({
    enabled: !showForm && activeTab !== "cartridges",
    queryKeyRoot: "printers",
    poll: () => Promise.resolve(),
  });

  const pollOneMut = useMutation({
    mutationFn: pollPrinter,
    onMutate: (id) => setPollingIds((s) => new Set(s).add(id)),
    onSettled: (_d, _e, id) => {
      setPollingIds((s) => { const n = new Set(s); n.delete(id); return n; });
      queryClient.invalidateQueries({ queryKey: ["printers"] });
    },
  });

  const extractError = (err: unknown): string => {
    if (err && typeof err === "object" && "response" in err) {
      const resp = (err as { response?: { data?: { detail?: string }; status?: number } }).response;
      const detail = resp?.data?.detail;
      if (detail === "Printer with this IP already exists") return "Принтер с таким IP уже существует";
      if (resp?.status === 409) return "Принтер с таким IP уже существует";
      if (detail) return detail;
    }
    return "Не удалось сохранить принтер";
  };

  const createMut = useMutation({
    mutationFn: createPrinter,
    onSuccess: () => {
      setFormError(null);
      queryClient.invalidateQueries({ queryKey: ["printers"] });
      setShowForm(false);
    },
    onError: (err) => setFormError(extractError(err)),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, ...rest }: { id: string; [key: string]: unknown }) =>
      updatePrinter(id, rest),
    onSuccess: () => {
      setFormError(null);
      queryClient.invalidateQueries({ queryKey: ["printers"] });
      setEditingPrinter(null);
      setShowForm(false);
    },
    onError: (err) => setFormError(extractError(err)),
  });

  const deleteMut = useMutation({
    mutationFn: deletePrinter,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["printers"] }),
  });

  const handleDelete = async (id: string) => {
    if (await confirm("Удалить принтер?", { danger: true, confirmText: "Удалить" })) deleteMut.mutate(id);
  };

  const printers = data?.data ?? [];
  const cartridgeStocks = cartridgeStockData?.data ?? [];
  const tonerPredictions = useMemo(
    () => (tonerPredictionsData?.data ?? []) as MLTonerPrediction[],
    [tonerPredictionsData],
  );
  const riskPredictions = useMemo(
    () => (riskPredictionsData?.data ?? []) as MLOfflineRiskPrediction[],
    [riskPredictionsData],
  );
  const tonerDaysByPrinter = useMemo(
    () =>
      tonerPredictions.reduce<Record<string, Partial<Record<"black" | "cyan" | "magenta" | "yellow", number>>>>(
        (acc, item) => {
          if (!item.printer_id || item.days_to_replacement == null) return acc;
          const color = item.toner_color as "black" | "cyan" | "magenta" | "yellow";
          if (!acc[item.printer_id]) acc[item.printer_id] = {};
          if (color === "black" || color === "cyan" || color === "magenta" || color === "yellow") {
            if (acc[item.printer_id][color] == null) {
              acc[item.printer_id][color] = item.days_to_replacement;
            }
          }
          return acc;
        },
        {},
      ),
    [tonerPredictions],
  );
  const riskByDeviceId = useMemo(
    () =>
      riskPredictions.reduce<Record<string, string>>((acc, item) => {
        if (item.device_id && !acc[item.device_id]) acc[item.device_id] = item.risk_level;
        return acc;
      }, {}),
    [riskPredictions],
  );
  const sortedPrinters = [...printers].sort((a, b) => {
    const rank = (value: boolean | null) => (value === true ? 0 : value === null ? 1 : 2);
    return rank(a.is_online) - rank(b.is_online);
  });
  const visiblePrinters = sortedPrinters.filter((printer) => {
    if (statusFilter === "online") return printer.is_online === true;
    if (statusFilter === "offline") return printer.is_online === false;
    if (statusFilter === "low_toner") {
      const levels = [printer.toner_black, printer.toner_cyan, printer.toner_magenta, printer.toner_yellow].filter(
        (l): l is number => l !== null && l >= 0,
      );
      return levels.some((l) => l <= 15);
    }
    return true;
  });

  const total = printers.length;
  const online = printers.filter((p) => p.is_online === true).length;
  const offline = printers.filter((p) => p.is_online === false).length;
  const lowToner = printerTab === "laser"
    ? printers.filter((p) => {
        const levels = [p.toner_black, p.toner_cyan, p.toner_magenta, p.toner_yellow].filter((l): l is number => l !== null && l >= 0);
        return levels.some((l) => l <= 15);
      }).length
    : 0;
  const showCopyMessage = (message: string) => {
    setCopyMessage(message);
    window.setTimeout(() => setCopyMessage((current) => (current === message ? null : current)), 1800);
  };

  return (
    <div className="space-y-6">
      <div className="app-panel p-3">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="relative w-full md:max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={
                activeTab === "cartridges"
                  ? "Поиск: название картриджа, модель принтера, цвет"
                  : "Умный поиск: магазин, модель, IP, host (A/А)"
              }
              className="app-input w-full pl-10 pr-4 py-2 text-sm"
            />
          </div>
          <div className="app-toolbar-actions flex flex-wrap gap-2">
            {copyMessage && (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
                <Check className="h-3.5 w-3.5" />
                {copyMessage}
              </span>
            )}
            <button
              onClick={() => pollAllMut.mutate()}
              disabled={pollAllMut.isPending || activeTab === "cartridges"}
              className="app-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50 transition"
            >
              <RefreshCw className={`h-4 w-4 ${pollAllMut.isPending ? "animate-spin" : ""}`} />
              {pollAllMut.isPending ? "Опрос..." : "Опросить все"}
            </button>
            {isSuperuser && activeTab !== "cartridges" && (
              <button
                onClick={() => { setEditingPrinter(null); setFormError(null); setShowForm(true); }}
                className="app-btn-secondary inline-flex items-center gap-2 px-4 py-2 text-sm transition"
              >
                <Plus className="h-4 w-4" />
                Добавить
              </button>
            )}
          </div>
        </div>
      </div>

      {activeTab !== "cartridges" && <PathSuspectBanner deviceKind="printer" />}

      {/* Stats (only for printer tabs) */}
      {activeTab !== "cartridges" && (
      <div className={`grid gap-4 ${printerTab === "laser" ? "grid-cols-2 sm:grid-cols-4" : "grid-cols-3"}`}>
        <Stat label="Всего" value={total} color="text-gray-900" bg="bg-gray-100" isActive={statusFilter === "all"} onClick={() => setStatusFilter("all")} />
        <Stat label="Онлайн" value={online} color="text-emerald-700" bg="bg-emerald-50" isActive={statusFilter === "online"} onClick={() => setStatusFilter("online")} />
        <Stat label="Оффлайн" value={offline} color="text-[var(--danger-fg)]" bg="bg-[var(--danger-bg)]" isActive={statusFilter === "offline"} onClick={() => setStatusFilter("offline")} />
        {printerTab === "laser" && (
          <Stat
            label="Мало тонера (<=15%)"
            value={lowToner}
            color="text-amber-700"
            bg="bg-amber-50"
            isActive={statusFilter === "low_toner"}
            onClick={() => setStatusFilter("low_toner")}
          />
        )}
      </div>
      )}

      {/* Sub-tabs */}
      <div className="app-tabbar flex gap-1 p-1.5 w-fit max-w-full overflow-x-auto app-compact-scroll">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => {
              setActiveTab(key);
              if (key !== "laser" && statusFilter === "low_toner") {
                setStatusFilter("all");
              }
              if (key !== "cartridges") setSelectedStockId(null);
            }}
            className={`app-tab inline-flex items-center gap-2 px-4 py-2 text-sm font-medium ${
              activeTab === key
                ? "active"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Printer grid */}
      {activeTab === "cartridges" ? (
        <CartridgeStockPanel
          rows={cartridgeStocks}
          movements={selectedMovementsData?.data ?? []}
          loading={isStockLoading}
          savingId={savingStockId}
          selectedId={selectedStockId}
          isSuperuser={isSuperuser}
          onSelect={(id) => setSelectedStockId((current) => (current === id ? null : id))}
          onAdjust={(id, quantity, minimum) => updateStockMut.mutate({ id, quantity, minimum })}
          onIssue={(id) => issueStockMut.mutate(id)}
        />
      ) : isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="app-panel p-4 space-y-4">
              <div className="flex items-center gap-3">
                <div className="app-skeleton h-10 w-10" />
                <div className="space-y-2 flex-1">
                  <div className="app-skeleton h-4 w-2/3" />
                  <div className="app-skeleton h-3 w-1/2" />
                </div>
              </div>
              <div className="app-skeleton h-24 w-full" />
              <div className="grid grid-cols-3 gap-2">
                <div className="app-skeleton h-8" />
                <div className="app-skeleton h-8" />
                <div className="app-skeleton h-8" />
              </div>
            </div>
          ))}
        </div>
      ) : visiblePrinters.length === 0 ? (
        <div className="app-empty text-center py-16 text-gray-400">
          <p className="text-lg">Нет {printerTab === "laser" ? "принтеров" : "этикеточных принтеров"}</p>
          <p className="text-sm mt-1">Добавьте {printerTab === "laser" ? "первый принтер" : "принтер этикеток"} для мониторинга</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {visiblePrinters.map((printer) =>
            printerTab === "laser" ? (
              <PrinterCard
                key={printer.id}
                printer={printer}
                onPoll={(id) => pollOneMut.mutate(id)}
                onEdit={(p) => { setEditingPrinter(p); setFormError(null); setShowForm(true); }}
                onDelete={handleDelete}
                isPolling={pollingIds.has(printer.id) || pollAllMut.isPending}
                isSuperuser={isSuperuser}
                showLowTonerDetails={statusFilter === "low_toner"}
                tonerPredictionDays={tonerDaysByPrinter[printer.id]}
                offlineRiskLevel={riskByDeviceId[printer.id]}
                onCopyToner={() => showCopyMessage("Картридж скопирован")}
              />
            ) : (
              <ZebraCard
                key={printer.id}
                printer={printer}
                onPoll={(id) => pollOneMut.mutate(id)}
                onEdit={(p) => { setEditingPrinter(p); setFormError(null); setShowForm(true); }}
                onDelete={handleDelete}
                isPolling={pollingIds.has(printer.id) || pollAllMut.isPending}
                isSuperuser={isSuperuser}
              />
            )
          )}
        </div>
      )}

      {/* Modal form */}
      {showForm && (
        <PrinterForm
          printer={editingPrinter}
          printerType={printerTab}
          loading={createMut.isPending || updateMut.isPending}
          error={formError}
          onClose={() => { setShowForm(false); setEditingPrinter(null); setFormError(null); }}
          onSave={(formData) => {
            setFormError(null);
            if (editingPrinter) {
              updateMut.mutate({ id: editingPrinter.id, ...formData });
            } else {
              createMut.mutate({ printer_type: printerTab, ...formData });
            }
          }}
        />
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  color,
  bg,
  isActive,
  onClick,
}: {
  label: string;
  value: number;
  color: string;
  bg: string;
  isActive?: boolean;
  onClick?: () => void;
}) {
  if (!onClick) {
    return (
      <div className={`app-stat ${bg} w-full px-4 py-3 text-left`}>
        <div className={`text-2xl font-bold ${color}`}>{value}</div>
        <div className="text-xs text-gray-500 mt-0.5">{label}</div>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={`app-stat ${bg} w-full px-4 py-3 text-left transition ${isActive ? "ring-2 ring-[var(--brand-border)]" : "hover:-translate-y-0.5 hover:shadow-md"}`}
    >
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </button>
  );
}
