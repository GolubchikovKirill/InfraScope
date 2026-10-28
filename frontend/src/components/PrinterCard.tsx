import { memo, useCallback, useRef, useState } from "react";
import {
  RefreshCw,
  Pencil,
  Trash2,
  ExternalLink,
  Printer as PrinterIcon,
  ChevronDown,
  BrainCircuit,
  MoreHorizontal,
  Copy,
  Check,
  AlertTriangle,
} from "lucide-react";
import type { Printer } from "../client";
import TonerBar from "./TonerBar";
import OnlineStatusBadge from "./OnlineStatusBadge";
import { useClickOutside } from "../hooks/useClickOutside";
import { useEscapeKey } from "../hooks/useEscapeKey";
import { describeOfflineReason } from "../lib/offlineReason";

interface Props {
  printer: Printer;
  onPoll: (id: string) => void;
  onEdit: (printer: Printer) => void;
  onDelete: (id: string) => void;
  isPolling: boolean;
  isSuperuser: boolean;
  showLowTonerDetails?: boolean;
  tonerPredictionDays?: Partial<Record<"black" | "cyan" | "magenta" | "yellow", number | null>>;
  /** band and basis behind each forecast, for its tooltip */
  tonerForecasts?: Partial<Record<"black" | "cyan" | "magenta" | "yellow", TonerForecastDetail>>;
  offlineRiskLevel?: "low" | "medium" | "high" | string | null;
  onCopyToner?: (text: string) => void;
}

export interface TonerForecastDetail {
  low: number | null;
  high: number | null;
  basis: string | null;
}

const BASIS_LABEL: Record<string, string> = {
  printer: "по расходу этого принтера",
  cartridge_model: "по среднему расходу этой модели картриджа",
  color: "по среднему расходу этого цвета",
  default: "по типовому расходу - данных пока мало",
};

function forecastTitle(days: number, detail: TonerForecastDetail | undefined): string {
  if (!detail) return `${days} дн. до замены`;
  const band =
    detail.low != null && detail.high != null
      ? ` (от ${Math.max(Math.round(detail.low), 0)} до ${Math.round(detail.high)} дн.)`
      : "";
  const basis = detail.basis ? `, ${BASIS_LABEL[detail.basis] ?? detail.basis}` : "";
  return `≈${days} дн. до замены${band}${basis}`;
}

const TONER_COLORS = {
  K: "black",
  C: "cyan",
  M: "magenta",
  Y: "yellow",
} as const;

type TonerKey = keyof typeof TONER_COLORS;

async function copyText(text: string): Promise<boolean> {
  const value = text.trim();
  if (!value || !navigator.clipboard) return false;
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}

function PrinterCard({
  printer,
  onPoll,
  onEdit,
  onDelete,
  isPolling,
  isSuperuser,
  showLowTonerDetails = false,
  tonerPredictionDays,
  tonerForecasts,
  offlineRiskLevel,
  onCopyToner,
}: Props) {
  const [isTonerModelsOpen, setIsTonerModelsOpen] = useState(false);
  const [isMlOpen, setIsMlOpen] = useState(false);
  const [isActionsOpen, setIsActionsOpen] = useState(false);
  const actionsRef = useRef<HTMLDivElement | null>(null);
  const [copiedToner, setCopiedToner] = useState<string | null>(null);
  const polledAt = printer.last_polled_at
    ? new Date(printer.last_polled_at).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })
    : null;
  const isOffline = printer.is_online === false;
  const hasTonerData =
    printer.toner_black !== null || printer.toner_cyan !== null || printer.toner_magenta !== null || printer.toner_yellow !== null;
  const isTonerStale = isOffline && hasTonerData;
  const tonerUpdatedAt = printer.toner_updated_at
    ? new Date(printer.toner_updated_at).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })
    : null;
  const isFlapping = printer.offline_count_24h >= 3;
  const lowTonerItems: Array<{ key: TonerKey; level: number | null; name: string | null }> = ([
    { key: "K", level: printer.toner_black, name: printer.toner_black_name },
    { key: "C", level: printer.toner_cyan, name: printer.toner_cyan_name },
    { key: "M", level: printer.toner_magenta, name: printer.toner_magenta_name },
    { key: "Y", level: printer.toner_yellow, name: printer.toner_yellow_name },
  ] as const).filter((item) => item.level !== null && item.level <= 15);
  const tonerModels: Array<{ key: TonerKey; name: string | null }> = ([
    { key: "K", name: printer.toner_black_name },
    { key: "C", name: printer.toner_cyan_name },
    { key: "M", name: printer.toner_magenta_name },
    { key: "Y", name: printer.toner_yellow_name },
  ] as const).filter((item) => Boolean(item.name));
  const mlPredictionEntries = (["black", "cyan", "magenta", "yellow"] as const)
    .map((key) => {
      const days = tonerPredictionDays?.[key];
      if (days == null) return null;
      const value = Math.max(Math.round(days), 0);
      const shortLabel = key[0].toUpperCase();
      const toneClass =
        value <= 7
          ? "ml-chip-critical"
          : value <= 21
            ? "ml-chip-warning"
            : "ml-chip-ok";
      return { key, shortLabel, value, toneClass };
    })
    .filter(Boolean) as Array<{ key: "black" | "cyan" | "magenta" | "yellow"; shortLabel: string; value: number; toneClass: string }>;
  const hasMlData = mlPredictionEntries.length > 0 || Boolean(offlineRiskLevel);
  const handleCopyToner = async (name: string | null) => {
    if (!name) return;
    if (await copyText(name)) {
      setCopiedToner(name);
      onCopyToner?.(name);
      window.setTimeout(() => setCopiedToner((current) => (current === name ? null : current)), 1600);
    }
  };
  const closeActions = useCallback(() => setIsActionsOpen(false), []);
  useClickOutside(actionsRef, isActionsOpen, closeActions);
  useEscapeKey(isActionsOpen, closeActions);

  return (
    <div className="app-panel app-card rounded-xl border shadow-sm hover:shadow-md transition flex flex-col">
      <div className="p-5 flex flex-1 flex-col gap-3.5">
        {/* Header: the store leads. People scan this page for a shop ("which
            store is out of toner"), not for a printer model - most of the fleet
            is the same three models - so the store is the card's title and the
            model steps down to the line beneath it. */}
        <div>
          <div className="flex items-start justify-between gap-2">
            <h3 className="app-card-store min-w-0" title={printer.store_name}>
              {printer.store_name}
            </h3>
            <div className="shrink-0 pt-0.5"><OnlineStatusBadge isOnline={printer.is_online} /></div>
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-1.5 app-card-subtitle" title={printer.model}>
            <span className="text-[var(--brand)]"><PrinterIcon className="h-3.5 w-3.5 shrink-0" /></span>
            <span className="truncate">{printer.model}</span>
          </div>
        </div>

        {/* Address line + warnings. The flapping hint used to sit under the
            status badge, where it squeezed the title down to "Brother …". */}
        {(printer.ip_address || printer.host_pc || printer.page_count != null) && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 app-card-meta">
            {printer.ip_address && <span className="app-mono">{printer.ip_address}</span>}
            {printer.host_pc && (
              <span>
                <span className="text-[var(--text-faint)]">ПК:</span>{" "}
                <span className="app-mono text-[var(--text-muted)]">{printer.host_pc}</span>
              </span>
            )}
            {printer.page_count != null && (
              <span title="Отпечатано страниц за всё время (счётчик принтера)">
                <span className="app-mono text-[var(--text-muted)]">{printer.page_count.toLocaleString("ru-RU")}</span>{" "}
                <span className="text-[var(--text-faint)]">стр.</span>
              </span>
            )}
          </div>
        )}
        {isFlapping && (
          <div
            className="app-chip-warn self-start"
            title="Принтер часто уходит в оффлайн и возвращается — возможна нестабильная связь на месте"
          >
            Нестабильная связь · {printer.offline_count_24h} за 24 ч
          </div>
        )}
        {isOffline && printer.reachability_reason && (
          <div className="flex items-center gap-1.5 text-xs text-[var(--danger-fg)]">
            <AlertTriangle className="h-3 w-3 shrink-0" />
            <span>{describeOfflineReason(printer.reachability_reason)}</span>
          </div>
        )}

        {/* Toner levels */}
        <div className={`space-y-1.5 transition-opacity ${isTonerStale ? "opacity-50" : ""}`}>
          <TonerBar
            label="K"
            level={printer.toner_black}
            color="bg-[var(--toner-k)]"
            bgColor="bg-gray-100"
            tonerName={printer.toner_black_name}
            isCopied={copiedToner === printer.toner_black_name}
            onCopy={() => handleCopyToner(printer.toner_black_name)}
          />
          <TonerBar
            label="C"
            level={printer.toner_cyan}
            color="bg-[var(--toner-c)]"
            bgColor="bg-cyan-50"
            tonerName={printer.toner_cyan_name}
            isCopied={copiedToner === printer.toner_cyan_name}
            onCopy={() => handleCopyToner(printer.toner_cyan_name)}
          />
          <TonerBar
            label="M"
            level={printer.toner_magenta}
            color="bg-[var(--toner-m)]"
            bgColor="bg-pink-50"
            tonerName={printer.toner_magenta_name}
            isCopied={copiedToner === printer.toner_magenta_name}
            onCopy={() => handleCopyToner(printer.toner_magenta_name)}
          />
          <TonerBar
            label="Y"
            level={printer.toner_yellow}
            color="bg-[var(--toner-y)]"
            bgColor="bg-yellow-50"
            tonerName={printer.toner_yellow_name}
            isCopied={copiedToner === printer.toner_yellow_name}
            onCopy={() => handleCopyToner(printer.toner_yellow_name)}
          />
        </div>
        {isTonerStale && (
          <div className="text-[11px] text-[var(--warn-fg)]">
            {tonerUpdatedAt ? `Данные картриджей от ${tonerUpdatedAt} (принтер сейчас оффлайн)` : "Принтер оффлайн — данные картриджей могут быть устаревшими"}
          </div>
        )}
        {tonerModels.length > 0 && (
          <div className="app-soft-panel rounded-lg px-3 py-2 text-xs text-gray-600">
            <button
              type="button"
              onClick={() => setIsTonerModelsOpen((prev) => !prev)}
              className="w-full flex items-center justify-between text-left font-medium text-gray-700"
            >
              <span>Модели картриджей</span>
              <ChevronDown className={`h-3.5 w-3.5 text-gray-500 transition-transform ${isTonerModelsOpen ? "rotate-180" : ""}`} />
            </button>
            {isTonerModelsOpen && (
              <div className="mt-2 grid gap-1 sm:grid-cols-2">
                {tonerModels.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => handleCopyToner(item.name)}
                    className="group inline-flex min-h-8 items-center justify-between gap-2 rounded-md border border-transparent px-2 py-1 text-left hover:border-[var(--brand-border)] hover:bg-white/70"
                    title="Скопировать модель картриджа"
                  >
                    <span>
                      {item.key}: <span className="font-medium text-gray-800">{item.name}</span>
                    </span>
                    {copiedToner === item.name ? (
                      <Check className="h-3.5 w-3.5 text-emerald-600" />
                    ) : (
                      <Copy className="h-3.5 w-3.5 text-gray-400 opacity-0 transition group-hover:opacity-100" />
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {hasMlData && (
          <div className="app-soft-panel rounded-lg px-2.5 py-1.5">
            <button
              type="button"
              onClick={() => setIsMlOpen((prev) => !prev)}
              className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-100/70 transition"
              title="Показать/скрыть прогноз"
            >
              <BrainCircuit className="h-3.5 w-3.5" />
              Прогноз
              <ChevronDown className={`h-3 w-3 transition-transform ${isMlOpen ? "rotate-180" : ""}`} />
            </button>
            {isMlOpen && (
              <div className="mt-1.5 space-y-1.5">
                {offlineRiskLevel && (
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      offlineRiskLevel === "high"
                        ? "bg-[var(--danger-bg)] text-[var(--danger-fg)]"
                        : offlineRiskLevel === "medium"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-emerald-100 text-emerald-700"
                    }`}
                  >
                    Риск: {offlineRiskLevel}
                  </span>
                )}
                {mlPredictionEntries.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {mlPredictionEntries.map((entry) => (
                      <span
                        key={entry.key}
                        className={`ml-chip inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${entry.toneClass}`}
                        title={forecastTitle(entry.value, tonerForecasts?.[entry.key])}
                      >
                        {entry.shortLabel}
                        <span>{entry.value} дн.</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        {showLowTonerDetails && lowTonerItems.length > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            <div className="font-medium mb-1">К замене:</div>
            <div className="space-y-0.5">
              {lowTonerItems.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => handleCopyToner(item.name)}
                  disabled={!item.name}
                  className="group flex w-full items-center justify-between gap-2 rounded-md px-1 py-0.5 text-left hover:bg-amber-100 disabled:cursor-default disabled:hover:bg-transparent"
                  title={item.name ? "Скопировать модель картриджа" : "Модель не указана"}
                >
                  <span>
                    {item.key}: {item.name || "модель не указана"} ({item.level}%)
                    {tonerPredictionDays?.[TONER_COLORS[item.key]] != null && (
                      <span
                        className="ml-1 text-[11px] text-amber-900/80"
                        title={forecastTitle(
                          Math.max(Math.round(tonerPredictionDays[TONER_COLORS[item.key]] || 0), 0),
                          tonerForecasts?.[TONER_COLORS[item.key]],
                        )}
                      >
                        ~{Math.max(Math.round(tonerPredictionDays[TONER_COLORS[item.key]] || 0), 0)} дн.
                      </span>
                    )}
                  </span>
                  {item.name && (
                    copiedToner === item.name ? (
                      <Check className="h-3.5 w-3.5 text-emerald-700" />
                    ) : (
                      <Copy className="h-3.5 w-3.5 text-amber-700/70 opacity-0 transition group-hover:opacity-100" />
                    )
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="mt-auto flex items-center justify-between pt-2 border-t border-[var(--border-faint)]">
          <span className="text-[11px] text-gray-400">
            {polledAt ? `Обновлено: ${polledAt}` : "Ещё не опрашивался"}
          </span>
          <div ref={actionsRef} className="relative flex items-center gap-1">
            <button
              onClick={() => onPoll(printer.id)}
              disabled={isPolling}
              className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-blue-600 transition disabled:opacity-40"
              title="Опросить"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isPolling ? "animate-spin" : ""}`} />
            </button>
            {printer.ip_address && (
              <a
                href={`http://${printer.ip_address}`}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-blue-600 transition"
                title="Веб-панель"
              >
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
            {isSuperuser && (
              <>
                <button
                  onClick={() => setIsActionsOpen((prev) => !prev)}
                  className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-slate-700 transition"
                  title="Дополнительные действия"
                >
                  <MoreHorizontal className="h-3.5 w-3.5" />
                </button>
                {isActionsOpen && (
                  <div className="absolute right-0 top-8 z-50 app-panel min-w-[140px] p-1.5 shadow-xl">
                    <button
                      onClick={() => { setIsActionsOpen(false); onEdit(printer); }}
                      className="w-full inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-100 transition"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      Редактировать
                    </button>
                    <button
                      onClick={() => { setIsActionsOpen(false); onDelete(printer.id); }}
                      className="w-full inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-[var(--danger-fg)] hover:bg-[var(--danger-bg)] transition"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Удалить
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

    </div>
  );
}

// Memoised: a fleet page renders dozens of these, and only the card whose
// printer or polling state changed needs to re-render.
export default memo(PrinterCard);
