import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Play, AlertTriangle } from "lucide-react";
import type { NetworkSwitch, DhcpDiagnostics, DhcpRole } from "../client";
import { getSwitchDhcp, runDhcpClearNow, updateSwitch } from "../client";
import { useConfirm } from "./ConfirmDialog";
import { showToast } from "../lib/toastBus";

const ROLE_LABEL: Record<DhcpRole, string> = {
  local_server: "DHCP раздаёт этот свитч",
  relay: "Свитч пересылает DHCP на другой сервер (helper-address)",
  external: "Свитч не раздаёт DHCP для этой VLAN (L2 / внешний сервер)",
};

// Server-side schedule is 04:10 and 16:10 UTC, 20 minutes ahead of the AP reboot.
const SCHEDULE_LABEL = "07:10 / 19:10 МСК";

function DiagnosticsView({ d }: { d: DhcpDiagnostics }) {
  const warnings: string[] = [];
  if (d.snooping_enabled && d.snooping_vlans.includes(d.vlan)) {
    if (d.arp_inspection_vlans.includes(d.vlan) || d.ip_source_guard) {
      warnings.push("DHCP snooping + ARP inspection / IP Source Guard: очистка snooping-таблицы отключила бы клиентов (скрипт её не трогает)");
    }
  }
  if (d.unsupported.length > 0) {
    warnings.push(`Свитч не поддерживает: ${d.unsupported.join("; ")}`);
  }
  const pool = d.pools[0];
  return (
    <div className="mt-2 space-y-1 border-t border-amber-200 pt-2 text-[11px] text-amber-900" data-testid="dhcp-diagnostics">
      <div className="font-medium">{ROLE_LABEL[d.role]}</div>
      {d.helper_addresses.length > 0 && <div>helper-address: {d.helper_addresses.join(", ")}</div>}
      {pool && (
        <div>
          Пул {pool.name}: занято {pool.leased_addresses ?? "?"} из {pool.total_addresses ?? "?"}
        </div>
      )}
      <div>
        Аренд в VLAN {d.vlan}: {d.ap_bindings.length} (всего на свитче {d.bindings_total}), конфликтов: {d.conflicts.length}
      </div>
      {d.planned_commands.length > 0 ? (
        <div>
          Очистка выполнит: {d.planned_commands.length} {d.planned_commands.length === 1 ? "команду" : "команд"}
          <pre className="mt-1 max-h-24 overflow-auto rounded bg-white/70 p-1 font-mono text-[10px]">
            {d.planned_commands.join("\n")}
          </pre>
        </div>
      ) : (
        d.skipped_reasons.map((r) => (
          <div key={r} className="text-amber-700">
            Очистка ничего не сделает: {r}
          </div>
        ))
      )}
      {warnings.map((w) => (
        <div key={w} className="flex items-start gap-1 text-[var(--danger-fg)]">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          <span>{w}</span>
        </div>
      ))}
    </div>
  );
}

export default function SwitchDhcpPanel({ sw }: { sw: NetworkSwitch }) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [diag, setDiag] = useState<DhcpDiagnostics | null>(null);

  const patchMut = useMutation({
    mutationFn: (patch: Record<string, unknown>) => updateSwitch(sw.id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["switches"] }),
  });

  const diagMut = useMutation({
    mutationFn: () => getSwitchDhcp(sw.id),
    onSuccess: setDiag,
    onError: () => showToast(`Не удалось прочитать DHCP со свитча ${sw.name}`, "error"),
  });

  const runMut = useMutation({
    mutationFn: () => runDhcpClearNow(sw.id),
    onSuccess: (r) => {
      const what =
        r.mode === "live"
          ? `очищено аренд: ${r.bindings_cleared ?? 0}, конфликтов: ${r.conflicts_cleared ?? 0}`
          : `тестовый прогон, команд: ${r.commands_planned}`;
      showToast(`DHCP ${sw.name}: ${r.skipped === "switch_unreachable" ? "свитч недоступен" : what}`, "success");
      diagMut.mutate();
    },
  });

  const live = sw.dhcp_clear_mode === "live";

  const handleRun = async () => {
    const ok = await confirm(
      live
        ? `Очистить DHCP на ${sw.name} сейчас?\n\nАренды AP-VLAN и список конфликтов будут реально удалены.`
        : `Тестовый прогон очистки DHCP для ${sw.name}.\n\nКоманды на свитч отправлены не будут.`,
      { danger: live, confirmText: "Запустить" },
    );
    if (ok) runMut.mutate();
  };

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="flex min-w-0 items-center gap-2 select-none">
          <button
            type="button"
            role="switch"
            aria-checked={sw.dhcp_clear_enabled}
            aria-label="Очистка DHCP по расписанию"
            onClick={() => patchMut.mutate({ dhcp_clear_enabled: !sw.dhcp_clear_enabled })}
            disabled={patchMut.isPending}
            className={`relative h-5 w-9 shrink-0 rounded-full transition disabled:opacity-50 ${
              sw.dhcp_clear_enabled ? "bg-[var(--brand-fill)]" : "bg-gray-300"
            }`}
            title={`Очистка DHCP-аренд и конфликтов на VLAN ${sw.ap_vlan} (${SCHEDULE_LABEL}, перед перезагрузкой ТД)`}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition ${
                sw.dhcp_clear_enabled ? "left-4" : "left-0.5"
              }`}
            />
          </button>
          <span className="text-[11px] text-amber-800">Очистка DHCP ({SCHEDULE_LABEL})</span>
        </label>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => patchMut.mutate({ dhcp_clear_mode: live ? "dry_run" : "live" })}
            disabled={patchMut.isPending || !sw.dhcp_clear_enabled}
            className={`rounded-md border px-1.5 py-0.5 text-[10px] font-medium transition disabled:opacity-40 ${
              live ? "border-red-300 bg-red-50 text-red-700" : "border-amber-300 bg-white text-amber-700"
            }`}
            title={live ? "Боевой режим: команды отправляются. Нажмите, чтобы вернуть тестовый." : "Тестовый режим: только лог. Нажмите, чтобы включить боевой."}
          >
            {live ? "боевой" : "тест"}
          </button>
          <button
            onClick={() => diagMut.mutate()}
            disabled={diagMut.isPending}
            className="rounded-lg border border-amber-300 bg-white p-1.5 text-amber-700 transition hover:bg-amber-100 disabled:opacity-40"
            title="Диагностика DHCP (только чтение)"
            aria-label="Диагностика DHCP"
          >
            <Search className={`h-3.5 w-3.5 ${diagMut.isPending ? "animate-pulse" : ""}`} />
          </button>
          <button
            onClick={handleRun}
            disabled={runMut.isPending || !sw.dhcp_clear_enabled}
            className="rounded-lg border border-amber-300 bg-white p-1.5 text-amber-700 transition hover:bg-amber-100 disabled:opacity-40"
            title={sw.dhcp_clear_enabled ? "Запустить очистку сейчас" : "Сначала включите очистку DHCP для этого свитча"}
            aria-label="Запустить очистку DHCP сейчас"
          >
            <Play className={`h-3.5 w-3.5 ${runMut.isPending ? "animate-pulse" : ""}`} />
          </button>
        </div>
      </div>
      {diag && <DiagnosticsView d={diag} />}
    </div>
  );
}
