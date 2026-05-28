import { useState } from "react";
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
} from "lucide-react";
import type { Printer } from "../client";
import TonerBar from "./TonerBar";

interface Props {
  printer: Printer;
  onPoll: (id: string) => void;
  onEdit: (printer: Printer) => void;
  onDelete: (id: string) => void;
  isPolling: boolean;
  isSuperuser: boolean;
  showLowTonerDetails?: boolean;
  tonerPredictionDays?: Partial<Record<"black" | "cyan" | "magenta" | "yellow", number | null>>;
  offlineRiskLevel?: "low" | "medium" | "high" | string | null;
  onCopyToner?: (text: string) => void;
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

function statusBadge(printer: Printer) {
  if (printer.is_online === null) {
    return <span className="inline-flex items-center gap-1 text-xs text-gray-400"><span className="h-2 w-2 rounded-full bg-gray-300" />Не опрошен</span>;
  }
  if (printer.is_online) {
    return <span className="inline-flex items-center gap-1 text-xs text-emerald-600"><span className="h-2 w-2 rounded-full bg-emerald-500" />Онлайн</span>;
  }
  return <span className="inline-flex items-center gap-1 text-xs text-red-500"><span className="h-2 w-2 rounded-full bg-red-500" />Оффлайн</span>;
}

function macCornerMeta(printer: Printer): { tone: "ok" | "warn" | "danger"; title: string } | null {
  if (!printer.mac_address && !printer.mac_status) return null;
  const macText = printer.mac_address ? ` (${printer.mac_address})` : "";
  if (printer.mac_status === "verified") {
    return { tone: "ok", title: `MAC подтвержден${macText}` };
  }
  if (printer.mac_status === "mismatch") {
    return { tone: "danger", title: `MAC не совпадает${macText}` };
  }
  return { tone: "warn", title: `MAC не подтвержден${macText}` };
}

export default function PrinterCard({
  printer,
  onPoll,
  onEdit,
  onDelete,
  isPolling,
  isSuperuser,
  showLowTonerDetails = false,
  tonerPredictionDays,
  offlineRiskLevel,
  onCopyToner,
}: Props) {
  const [isTonerModelsOpen, setIsTonerModelsOpen] = useState(false);
  const [isMlOpen, setIsMlOpen] = useState(false);
  const [isActionsOpen, setIsActionsOpen] = useState(false);
  const [copiedToner, setCopiedToner] = useState<string | null>(null);
  const polledAt = printer.last_polled_at
    ? new Date(printer.last_polled_at).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })
    : null;
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
  const macCorner = macCornerMeta(printer);
  const hasMlData = mlPredictionEntries.length > 0 || Boolean(offlineRiskLevel);
  const handleCopyToner = async (name: string | null) => {
    if (!name) return;
    if (await copyText(name)) {
      setCopiedToner(name);
      onCopyToner?.(name);
      window.setTimeout(() => setCopiedToner((current) => (current === name ? null : current)), 1600);
    }
  };

  return (
    <div className="app-panel app-card rounded-xl border shadow-sm hover:shadow-md transition flex flex-col">
      {macCorner && (
        <div
          className={`app-card-corner app-card-corner-${macCorner.tone}`}
          title={macCorner.title}
          aria-label={macCorner.title}
        />
      )}
      <div className="p-5 flex flex-col gap-4">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-blue-50 p-2">
              <PrinterIcon className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <div className="font-medium text-sm text-gray-900">{printer.model}</div>
              <div className="text-xs text-gray-500">{printer.store_name}</div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            {statusBadge(printer)}
          </div>
        </div>

        {/* IP + MAC */}
        {printer.ip_address && (
          <div className="text-xs text-gray-400 font-mono">{printer.ip_address}</div>
        )}
        {printer.host_pc && (
          <div className="text-xs text-gray-500">
            <span className="text-gray-400">Hostname:</span> {printer.host_pc}
          </div>
        )}

        {/* Toner levels */}
        <div className="space-y-1.5">
          <TonerBar
            label="K"
            level={printer.toner_black}
            color="bg-gray-800"
            bgColor="bg-gray-100"
            tonerName={printer.toner_black_name}
            isCopied={copiedToner === printer.toner_black_name}
            onCopy={() => handleCopyToner(printer.toner_black_name)}
          />
          <TonerBar
            label="C"
            level={printer.toner_cyan}
            color="bg-cyan-500"
            bgColor="bg-cyan-50"
            tonerName={printer.toner_cyan_name}
            isCopied={copiedToner === printer.toner_cyan_name}
            onCopy={() => handleCopyToner(printer.toner_cyan_name)}
          />
          <TonerBar
            label="M"
            level={printer.toner_magenta}
            color="bg-pink-500"
            bgColor="bg-pink-50"
            tonerName={printer.toner_magenta_name}
            isCopied={copiedToner === printer.toner_magenta_name}
            onCopy={() => handleCopyToner(printer.toner_magenta_name)}
          />
          <TonerBar
            label="Y"
            level={printer.toner_yellow}
            color="bg-yellow-400"
            bgColor="bg-yellow-50"
            tonerName={printer.toner_yellow_name}
            isCopied={copiedToner === printer.toner_yellow_name}
            onCopy={() => handleCopyToner(printer.toner_yellow_name)}
          />
        </div>
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
                    className="group inline-flex min-h-8 items-center justify-between gap-2 rounded-md border border-transparent px-2 py-1 text-left hover:border-rose-200 hover:bg-white/70"
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
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      offlineRiskLevel === "high"
                        ? "bg-red-100 text-red-700"
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
                        title={`${entry.value} дн. до замены (${entry.key})`}
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
                      <span className="ml-1 text-[11px] text-amber-900/80">
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
        <div className="flex items-center justify-between pt-2 border-t border-gray-100">
          <span className="text-[11px] text-gray-400">
            {polledAt ? `Обновлено: ${polledAt}` : "Ещё не опрашивался"}
          </span>
          <div className="relative flex items-center gap-1">
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
                  <div className="absolute right-0 top-8 z-20 app-panel min-w-[140px] p-1.5">
                    <button
                      onClick={() => { setIsActionsOpen(false); onEdit(printer); }}
                      className="w-full inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-100 transition"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      Редактировать
                    </button>
                    <button
                      onClick={() => { setIsActionsOpen(false); onDelete(printer.id); }}
                      className="w-full inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-rose-600 hover:bg-rose-50 transition"
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
