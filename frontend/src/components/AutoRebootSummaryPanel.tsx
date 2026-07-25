import { useQuery } from "@tanstack/react-query";
import { Wifi, CheckCircle2, AlertTriangle, SkipForward } from "lucide-react";
import { getAutoRebootSummary } from "../client";

function MiniStat({ value, label, tone }: { value: number; label: string; tone: "ok" | "danger" | "muted" }) {
  const toneClass =
    tone === "ok" ? "text-emerald-700" : tone === "danger" ? "text-red-700" : "text-gray-500";
  return (
    <div className="text-center">
      <div className={`text-lg font-bold ${toneClass}`}>{value}</div>
      <div className="text-[11px] text-gray-500 whitespace-nowrap">{label}</div>
    </div>
  );
}

export default function AutoRebootSummaryPanel() {
  const { data } = useQuery({
    queryKey: ["auto-reboot-summary"],
    queryFn: () => getAutoRebootSummary(24),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  if (!data || !data.last_cycle_at) return null;

  const hasFailures = data.aps_failed > 0;
  const lastCycleText = new Date(data.last_cycle_at).toLocaleString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  });

  return (
    <div
      className={`app-panel rounded-xl border p-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4 ${
        hasFailures ? "border-red-200 bg-red-50" : "border-emerald-200 bg-emerald-50"
      }`}
    >
      <div className="flex items-center gap-3">
        <div className={`rounded-lg p-2 ${hasFailures ? "bg-red-100" : "bg-emerald-100"}`}>
          {hasFailures ? (
            <AlertTriangle className="h-5 w-5 text-red-600" />
          ) : (
            <Wifi className="h-5 w-5 text-emerald-600" />
          )}
        </div>
        <div>
          <div className="text-sm font-medium text-gray-900">Автоперезагрузка точек доступа</div>
          <div className="text-xs text-gray-500">Последний цикл: {lastCycleText}</div>
        </div>
      </div>
      <div className="flex items-center gap-5 sm:ml-auto">
        <MiniStat value={data.switches_processed} label="магазинов" tone="muted" />
        <MiniStat value={data.aps_rebooted_ok} label="перезагружено" tone="ok" />
        {data.aps_failed > 0 && (
          <div className="flex items-center gap-1.5">
            <AlertTriangle className="h-4 w-4 text-red-500" />
            <MiniStat value={data.aps_failed} label="не вернулись" tone="danger" />
          </div>
        )}
        {data.switches_skipped > 0 && (
          <div className="flex items-center gap-1.5">
            <SkipForward className="h-4 w-4 text-gray-400" />
            <MiniStat value={data.switches_skipped} label="пропущено" tone="muted" />
          </div>
        )}
        {!hasFailures && (
          <CheckCircle2 className="h-5 w-5 text-emerald-500 shrink-0" />
        )}
      </div>
    </div>
  );
}
