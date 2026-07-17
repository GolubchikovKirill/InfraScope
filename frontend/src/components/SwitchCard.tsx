import { useCallback, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  RefreshCw, Pencil, Trash2, Network, Wifi, Clock, Cpu,
  ExternalLink, RotateCcw, ChevronDown, ChevronUp, Zap, Radio, MoreHorizontal,
} from "lucide-react";
import type { NetworkSwitch, AccessPoint } from "../client";
import { getSwitchAPs, rebootAP, updateSwitch } from "../client";
import { useClickOutside } from "../hooks/useClickOutside";
import { useEscapeKey } from "../hooks/useEscapeKey";

interface Props {
  sw: NetworkSwitch;
  onPoll: (id: string) => void;
  onEdit: (sw: NetworkSwitch) => void;
  onDelete: (id: string) => void;
  onOpenPorts: (sw: NetworkSwitch) => void;
  isPolling: boolean;
  isSuperuser: boolean;
}

function statusBadge(sw: NetworkSwitch) {
  if (sw.is_online === null) {
    return <span className="inline-flex items-center gap-1 text-xs text-gray-400"><span className="h-2 w-2 rounded-full bg-gray-300" />Не проверен</span>;
  }
  if (sw.is_online) {
    return <span className="inline-flex items-center gap-1 text-xs text-emerald-600"><span className="h-2 w-2 rounded-full bg-emerald-500" />Онлайн</span>;
  }
  return <span className="inline-flex items-center gap-1 text-xs text-red-500"><span className="h-2 w-2 rounded-full bg-red-500" />Оффлайн</span>;
}

function APRow({ ap, switchId, isSuperuser }: { ap: AccessPoint; switchId: string; isSuperuser: boolean }) {
  const queryClient = useQueryClient();
  const [rebooting, setRebooting] = useState(false);

  const rebootMut = useMutation({
    mutationFn: () => rebootAP(switchId, ap.port),
    onSettled: () => {
      setRebooting(false);
      queryClient.invalidateQueries({ queryKey: ["switch-aps", switchId] });
    },
  });

  const handleReboot = () => {
    if (confirm(`Перезагрузить точку доступа на порту ${ap.port}?`)) {
      setRebooting(true);
      rebootMut.mutate();
    }
  };

  return (
    <div className="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-gray-50 group text-xs">
      <Radio className="h-3.5 w-3.5 text-rose-500 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-gray-800">
            {ap.cdp_name || ap.mac_address}
          </span>
          {ap.cdp_platform && (
            <span className="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">{ap.cdp_platform}</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-gray-500 mt-0.5">
          <span className="font-mono">{ap.port}</span>
          {ap.ip_address && <span className="font-mono">{ap.ip_address}</span>}
          <span className="font-mono text-gray-400">{ap.mac_address}</span>
          {ap.poe_power && ap.poe_power !== "0.0W" && (
            <span className="inline-flex items-center gap-0.5 text-amber-600">
              <Zap className="h-3 w-3" />{ap.poe_power}
            </span>
          )}
        </div>
      </div>
      {isSuperuser && (
        <button
          onClick={handleReboot}
          disabled={rebooting}
          className="p-1.5 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-red-50 text-gray-400 hover:text-red-600 transition disabled:opacity-40"
          title="Перезагрузить ТД (PoE cycle)"
        >
          <RotateCcw className={`h-3.5 w-3.5 ${rebooting ? "animate-spin" : ""}`} />
        </button>
      )}
    </div>
  );
}

export default function SwitchCard({ sw, onPoll, onEdit, onDelete, onOpenPorts, isPolling, isSuperuser }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [isActionsOpen, setIsActionsOpen] = useState(false);
  const actionsRef = useRef<HTMLDivElement | null>(null);
  const queryClient = useQueryClient();

  const { data: aps, isLoading: loadingAPs } = useQuery({
    queryKey: ["switch-aps", sw.id],
    queryFn: () => getSwitchAPs(sw.id),
    enabled: expanded,
    staleTime: 30_000,
  });

  const autoRebootMut = useMutation({
    mutationFn: (patch: Record<string, unknown>) => updateSwitch(sw.id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["switches"] }),
  });

  const polledAt = sw.last_polled_at
    ? new Date(sw.last_polled_at).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })
    : null;
  const closeActions = useCallback(() => setIsActionsOpen(false), []);
  useClickOutside(actionsRef, isActionsOpen, closeActions);
  useEscapeKey(isActionsOpen, closeActions);

  return (
    <div className={`app-panel app-card rounded-xl border shadow-sm hover:shadow-md transition flex flex-col ${isActionsOpen ? "relative z-30" : ""}`}>
      <div className="p-5 flex flex-col gap-3">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-rose-50 p-2">
              <Network className="h-5 w-5 text-rose-600" />
            </div>
            <div>
              <div className="font-medium text-sm text-gray-900">{sw.name}</div>
              <div className="text-xs text-gray-500">{sw.model_info || sw.vendor.toUpperCase()}</div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            {statusBadge(sw)}
            <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-rose-50 text-rose-700">
              VLAN {sw.ap_vlan}
            </span>
          </div>
        </div>

        {/* Switch info */}
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <Wifi className="h-3 w-3 text-gray-400" />
            <span className="font-mono">{sw.ip_address}:{sw.ssh_port}</span>
          </div>

          {sw.hostname && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Network className="h-3 w-3 text-gray-400" />
              <span>{sw.hostname}</span>
            </div>
          )}

          {sw.ios_version && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Cpu className="h-3 w-3 text-gray-400" />
              <span className="truncate" title={sw.ios_version}>{sw.ios_version}</span>
            </div>
          )}

          {sw.uptime && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Clock className="h-3 w-3 text-gray-400" />
              <span className="truncate" title={sw.uptime}>Uptime: {sw.uptime}</span>
            </div>
          )}
        </div>

        {/* Access Points toggle */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 text-xs font-medium text-rose-600 hover:text-rose-700 transition mt-1"
        >
          <Radio className="h-3.5 w-3.5" />
          Точки доступа (VLAN {sw.ap_vlan})
          {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {aps && <span className="text-gray-400 font-normal">({aps.length})</span>}
        </button>
        <button
          onClick={() => onOpenPorts(sw)}
          className="flex items-center gap-1.5 text-xs font-medium text-rose-600 hover:text-rose-700 transition"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          Порты свитча
        </button>

        {/* Scheduled AP auto-reboot: pilot feature, VLAN 20 only, superuser-only.
            The actual store allowlist lives server-side (AUTO_REBOOT_AP_ALLOWED_STORES) -
            this toggle alone does not guarantee the schedule will act on this switch. */}
        {isSuperuser && sw.vendor === "cisco" && sw.ap_vlan === 20 && (
          <div className="flex items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <button
                type="button"
                role="switch"
                aria-checked={sw.auto_reboot_aps_enabled}
                onClick={() =>
                  autoRebootMut.mutate({ auto_reboot_aps_enabled: !sw.auto_reboot_aps_enabled })
                }
                disabled={autoRebootMut.isPending}
                className={`relative h-5 w-9 shrink-0 rounded-full transition disabled:opacity-50 ${
                  sw.auto_reboot_aps_enabled ? "bg-rose-600" : "bg-gray-300"
                }`}
                title="Автоперезагрузка Wi-Fi точек на VLAN 20 (07:30 и 19:30 МСК)"
              >
                <span
                  className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition ${
                    sw.auto_reboot_aps_enabled ? "left-4" : "left-0.5"
                  }`}
                />
              </button>
              <span className="text-[11px] text-amber-800">
                Авто-перезагрузка ТД (07:30 / 19:30 МСК)
              </span>
            </label>
            {sw.auto_reboot_aps_enabled && (
              <select
                value={sw.auto_reboot_mode}
                onChange={(e) => autoRebootMut.mutate({ auto_reboot_mode: e.target.value })}
                disabled={autoRebootMut.isPending}
                className="text-[11px] rounded border border-amber-300 bg-white px-1.5 py-0.5 text-amber-900"
                title="Тестовый режим только логирует; боевой реально перезагружает"
              >
                <option value="dry_run">Тест (без реальной перезагрузки)</option>
                <option value="live">Боевой режим</option>
              </select>
            )}
          </div>
        )}

        {/* AP List */}
        {expanded && (
          <div className="border-t border-gray-100 pt-2 -mx-2">
            {loadingAPs ? (
              <div className="flex items-center justify-center py-4">
                <RefreshCw className="h-4 w-4 animate-spin text-rose-500" />
                <span className="ml-2 text-xs text-gray-400">Загрузка...</span>
              </div>
            ) : aps && aps.length > 0 ? (
              <div className="space-y-0.5 max-h-80 overflow-y-auto">
                {aps.map((ap) => (
                  <APRow key={ap.mac_address} ap={ap} switchId={sw.id} isSuperuser={isSuperuser} />
                ))}
              </div>
            ) : (
              <div className="text-xs text-gray-400 text-center py-3">
                Нет устройств на VLAN {sw.ap_vlan}
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-2 border-t border-gray-100">
          <span className="text-[11px] text-gray-400">
            {polledAt ? `Обновлено: ${polledAt}` : "Ещё не опрашивался"}
          </span>
          <div ref={actionsRef} className="relative flex items-center gap-1">
            <button
              onClick={() => onPoll(sw.id)}
              disabled={isPolling}
              className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-rose-600 transition disabled:opacity-40"
              title="Опросить"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isPolling ? "animate-spin" : ""}`} />
            </button>
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
                      onClick={() => { setIsActionsOpen(false); onEdit(sw); }}
                      className="w-full inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-100 transition"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      Редактировать
                    </button>
                    <button
                      onClick={() => { setIsActionsOpen(false); onDelete(sw.id); }}
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
