import { useQuery } from "@tanstack/react-query";
import { Wifi, CheckCircle2, AlertTriangle, SkipForward } from "lucide-react";
import { getAutoRebootSummary } from "../client";

function MiniStat({ value, label, tone }: { value: number; label: string; tone: "ok" | "danger" | "muted" }) {
  const toneClass =
    tone === "ok" ? "text-emerald-700" : tone === "danger" ? "text-[var(--danger-fg)]" : "text-gray-500";
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

  if (!data || (!data.last_cycle_at && data.aps_needing_attention === 0 && data.switches_needing_attention === 0)) return null;

  const hasFailures = data.aps_failed > 0 || data.aps_needing_attention > 0 || data.switches_needing_attention > 0;
  const lastCycleText = data.last_cycle_at
    ? new Date(data.last_cycle_at).toLocaleString("ru-RU", {
        hour: "2-digit",
        minute: "2-digit",
        day: "2-digit",
        month: "2-digit",
      })
    : null;

  return (
    <div
      className={`app-panel rounded-xl border p-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4 ${
        hasFailures ? "border-[var(--danger-border)] bg-[var(--danger-bg)]" : "border-emerald-200 bg-emerald-50"
      }`}
    >
      <div className="flex items-center gap-3">
        <div className={`rounded-lg p-2 ${hasFailures ? "bg-[var(--danger-bg)]" : "bg-emerald-100"}`}>
          {hasFailures ? (
            <AlertTriangle className="h-5 w-5 text-[var(--danger-fg)]" />
          ) : (
            <Wifi className="h-5 w-5 text-emerald-600" />
          )}
        </div>
        <div>
          <div className="text-sm font-medium text-gray-900">Автоперезагрузка точек доступа</div>
          <div className="text-xs text-gray-500">
            {lastCycleText ? `Последний цикл: ${lastCycleText}` : `За последние ${data.window_hours} ч циклов не было`}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-5 sm:ml-auto">
        <MiniStat value={data.switches_processed} label="магазинов" tone="muted" />
        <MiniStat value={data.aps_rebooted_ok} label="перезагружено" tone="ok" />
        {data.aps_failed > 0 && (
          <div className="flex items-center gap-1.5">
            <AlertTriangle className="h-4 w-4 text-[var(--danger-fg)]" />
            <MiniStat value={data.aps_failed} label="не вернулись" tone="danger" />
          </div>
        )}
        {data.aps_needing_attention > 0 && (
          <div className="flex items-center gap-1.5" title="Точки, исключённые из автоперезагрузки после нескольких неудачных циклов подряд — нужна проверка на месте">
            <AlertTriangle className="h-4 w-4 text-[var(--danger-fg)]" />
            <MiniStat value={data.aps_needing_attention} label="точки требуют проверки" tone="danger" />
          </div>
        )}
        {data.switches_needing_attention > 0 && (
          <div className="flex items-center gap-1.5" title="Свитчи, у которых цикл авто-перезагрузки не может отработать несколько раз подряд — не отвечают по SSH или не находят точек на VLAN">
            <AlertTriangle className="h-4 w-4 text-[var(--danger-fg)]" />
            <MiniStat value={data.switches_needing_attention} label="свитчи требуют проверки" tone="danger" />
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
