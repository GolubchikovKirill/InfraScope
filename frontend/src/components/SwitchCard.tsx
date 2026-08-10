import { useCallback, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  RefreshCw, Pencil, Trash2, Network, Wifi, Clock, Cpu,
  ExternalLink, RotateCcw, ChevronDown, ChevronUp, Zap, Radio, MoreHorizontal,
  AlertTriangle, History, Play, EyeOff,
} from "lucide-react";
import type { NetworkSwitch, AccessPoint } from "../client";
import {
  getSwitchAPs, rebootAP, updateSwitch, setApExcluded, runAutoRebootNow, getAutoRebootHistory,
} from "../client";
import { useClickOutside } from "../hooks/useClickOutside";
import { useEscapeKey } from "../hooks/useEscapeKey";
import { useConfirm } from "./ConfirmDialog";
import { showToast } from "../lib/toastBus";
import OnlineStatusBadge from "./OnlineStatusBadge";

interface Props {
  sw: NetworkSwitch;
  onPoll: (id: string) => void;
  onEdit: (sw: NetworkSwitch) => void;
  onDelete: (id: string) => void;
  onOpenPorts: (sw: NetworkSwitch) => void;
  isPolling: boolean;
  isSuperuser: boolean;
}

function APRow({ ap, switchId, isSuperuser }: { ap: AccessPoint; switchId: string; isSuperuser: boolean }) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [rebooting, setRebooting] = useState(false);
  const isHung = !ap.is_responding;

  const invalidateAps = () => queryClient.invalidateQueries({ queryKey: ["switch-aps", switchId] });

  const rebootMut = useMutation({
    mutationFn: () => rebootAP(switchId, ap.port, ap.mac_address),
    onSuccess: (result) => {
      if (result.back_online === false) {
        showToast(`Точка на порту ${ap.port} перезагружена, но не вернулась онлайн — проверьте на месте`, "error");
      } else {
        showToast(`Точка на порту ${ap.port} перезагружена${result.back_online ? " и вернулась онлайн" : ""}`, "success");
      }
    },
    onSettled: () => {
      setRebooting(false);
      invalidateAps();
    },
  });

  const excludeMut = useMutation({
    mutationFn: (excluded: boolean) => setApExcluded(switchId, ap.mac_address, excluded),
    onSuccess: invalidateAps,
  });

  const handleReboot = async () => {
    if (
      await confirm(
        `Перезагрузить точку доступа на порту ${ap.port}?\n\nПроверка возврата онлайн может занять до нескольких минут.`,
        { danger: true, confirmText: "Перезагрузить" },
      )
    ) {
      setRebooting(true);
      rebootMut.mutate();
    }
  };

  const lastSeen = ap.last_seen_at
    ? new Date(ap.last_seen_at).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })
    : null;

  return (
    <div className={`flex items-center gap-3 py-2 px-3 rounded-lg group text-xs ${isHung ? "bg-[var(--danger-bg)]" : "hover:bg-[var(--surface-2)]"}`}>
      {isHung ? (
        <AlertTriangle className="h-3.5 w-3.5 text-[var(--danger-fg)] shrink-0" />
      ) : (
        <Radio className="h-3.5 w-3.5 text-[var(--brand)] shrink-0" />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className={`font-medium ${isHung ? "text-[var(--danger-fg)]" : "text-[var(--text-default)]"}`}>
            {ap.cdp_name || ap.mac_address}
          </span>
          {isHung && (
            <span className="text-[11px] text-[var(--danger-fg)] bg-[var(--danger-bg)] px-1.5 py-0.5 rounded font-medium" title={lastSeen ? `Последний раз отвечала: ${lastSeen}` : undefined}>
              не отвечает
            </span>
          )}
          {ap.cdp_platform && (
            <span className="text-[11px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">{ap.cdp_platform}</span>
          )}
          {ap.needs_attention_since ? (
            <span
              className="text-[11px] text-white bg-[var(--danger-fg)] px-1.5 py-0.5 rounded inline-flex items-center gap-0.5 font-medium"
              title={
                `Не восстанавливается автоматически с ${new Date(ap.needs_attention_since).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })}` +
                (ap.consecutive_no_power_skips > ap.consecutive_reboot_failures
                  ? ` — порт без питания ${ap.consecutive_no_power_skips} циклов подряд`
                  : ` — не вернулась онлайн ${ap.consecutive_reboot_failures} перезагрузок подряд`) +
                ". Автоперезагрузка отключена для этой точки, нужна проверка на месте."
              }
            >
              <AlertTriangle className="h-2.5 w-2.5" />требует проверки на месте
            </span>
          ) : (
            ap.exclude_from_auto_reboot && (
              <span className="text-[11px] text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded inline-flex items-center gap-0.5">
                <EyeOff className="h-2.5 w-2.5" />искл. из автоперезагрузки
              </span>
            )
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-gray-500 mt-0.5">
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
        // Stays visible rather than appearing on hover: these buttons power-cycle
        // a live access point, and a control that only exists on hover is
        // unreachable on touch and invisible to keyboard focus.
        <div className="flex items-center gap-1 opacity-70 transition group-hover:opacity-100 focus-within:opacity-100">
          <button
            onClick={() => excludeMut.mutate(!ap.exclude_from_auto_reboot)}
            disabled={excludeMut.isPending}
            className="app-icon-btn hover:bg-gray-100 text-gray-400 hover:text-gray-700 disabled:opacity-40"
            title={
              ap.exclude_from_auto_reboot
                ? ap.needs_attention_since
                  ? "Отметить как исправлено и вернуть в автоперезагрузку"
                  : "Вернуть в автоперезагрузку"
                : "Исключить из автоперезагрузки"
            }
            aria-label={
              ap.exclude_from_auto_reboot
                ? `Вернуть точку ${ap.cdp_name || ap.mac_address} в автоперезагрузку`
                : `Исключить точку ${ap.cdp_name || ap.mac_address} из автоперезагрузки`
            }
          >
            <EyeOff className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={handleReboot}
            disabled={rebooting}
            className="app-icon-btn hover:bg-[var(--danger-bg)] text-gray-400 hover:text-[var(--danger-fg)] transition disabled:opacity-40"
            title="Перезагрузить ТД (PoE cycle)"
            aria-label={`Перезагрузить точку доступа на порту ${ap.port}`}
          >
            <RotateCcw className={`h-3.5 w-3.5 ${rebooting ? "animate-spin" : ""}`} />
          </button>
        </div>
      )}
    </div>
  );
}

export default function SwitchCard({ sw, onPoll, onEdit, onDelete, onOpenPorts, isPolling, isSuperuser }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const [isActionsOpen, setIsActionsOpen] = useState(false);
  const actionsRef = useRef<HTMLDivElement | null>(null);
  const queryClient = useQueryClient();
  const confirm = useConfirm();

  const { data: aps, isLoading: loadingAPs } = useQuery({
    queryKey: ["switch-aps", sw.id],
    queryFn: () => getSwitchAPs(sw.id),
    enabled: expanded,
    staleTime: 30_000,
  });

  const { data: history, isLoading: loadingHistory } = useQuery({
    queryKey: ["switch-auto-reboot-history", sw.id],
    queryFn: () => getAutoRebootHistory(sw.id),
    enabled: historyExpanded,
    staleTime: 30_000,
  });

  const autoRebootMut = useMutation({
    mutationFn: (patch: Record<string, unknown>) => updateSwitch(sw.id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["switches"] }),
  });

  const runNowMut = useMutation({
    mutationFn: () => runAutoRebootNow(sw.id),
    onSuccess: () => {
      showToast(`Цикл автоперезагрузки для ${sw.name} завершён`, "success");
      queryClient.invalidateQueries({ queryKey: ["switch-aps", sw.id] });
      queryClient.invalidateQueries({ queryKey: ["switch-auto-reboot-history", sw.id] });
    },
  });

  const handleRunNow = async () => {
    if (
      await confirm(
        `Запустить цикл автоперезагрузки точек доступа для ${sw.name} сейчас?\n\nТочки будут реально перезагружены.`,
        { danger: true, confirmText: "Запустить" },
      )
    ) {
      runNowMut.mutate();
    }
  };

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
            <div className="app-entity-icon">
              <Network className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="app-card-title truncate">{sw.name}</div>
              <div className="app-card-meta truncate">{sw.model_info || sw.vendor.toUpperCase()}</div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <OnlineStatusBadge isOnline={sw.is_online} />
            <span className="text-[11px] px-1.5 py-0.5 rounded-full font-medium bg-[var(--brand-soft)] text-[var(--brand)]">
              VLAN {sw.ap_vlan}
            </span>
          </div>
        </div>

        {sw.switch_needs_attention_since && (
          <div
            className="flex items-center gap-1.5 rounded-lg bg-[var(--danger-bg)] border border-[var(--danger-border)] px-2.5 py-1.5 text-xs text-[var(--danger-fg)]"
            title={`С ${new Date(sw.switch_needs_attention_since).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })} автоперезагрузка точек доступа не может нормально отработать на этом свитче несколько циклов подряд — не отвечает по SSH или не находит ни одной точки на VLAN. Требует проверки (доступ/конфигурация).`}
          >
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span className="font-medium">Автоперезагрузка не работает на этом свитче — нужна проверка</span>
          </div>
        )}

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
          className="flex items-center gap-1.5 text-xs font-medium text-[var(--brand)] hover:text-[var(--brand-strong)] transition mt-1"
        >
          <Radio className="h-3.5 w-3.5" />
          Точки доступа (VLAN {sw.ap_vlan})
          {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {aps && <span className="text-gray-400 font-normal">({aps.length})</span>}
        </button>
        <button
          onClick={() => onOpenPorts(sw)}
          className="flex items-center gap-1.5 text-xs font-medium text-[var(--brand)] hover:text-[var(--brand-strong)] transition"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          Порты свитча
        </button>

        {/* Scheduled AP auto-reboot: VLAN 20 only, superuser-only. The actual
            store allowlist lives server-side (AUTO_REBOOT_AP_ALLOWED_STORES) -
            this toggle alone does not guarantee the schedule will act on this switch. */}
        {isSuperuser && sw.vendor === "cisco" && sw.ap_vlan === 20 && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
            <label className="flex items-center gap-2 cursor-pointer select-none min-w-0">
              <button
                type="button"
                role="switch"
                aria-checked={sw.auto_reboot_aps_enabled}
                onClick={() =>
                  autoRebootMut.mutate({
                    auto_reboot_aps_enabled: !sw.auto_reboot_aps_enabled,
                    auto_reboot_mode: "live",
                  })
                }
                disabled={autoRebootMut.isPending}
                className={`relative h-5 w-9 shrink-0 rounded-full transition disabled:opacity-50 ${
                  sw.auto_reboot_aps_enabled ? "bg-[var(--brand-fill)]" : "bg-gray-300"
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
            <div className="flex items-center gap-1.5">
              <button
                onClick={handleRunNow}
                disabled={runNowMut.isPending}
                className="p-1.5 rounded-lg bg-white border border-amber-300 text-amber-700 hover:bg-amber-100 transition disabled:opacity-40"
                title="Запустить цикл автоперезагрузки сейчас (не дожидаясь 07:30/19:30)"
              >
                <Play className={`h-3.5 w-3.5 ${runNowMut.isPending ? "animate-pulse" : ""}`} />
              </button>
            </div>
          </div>
        )}

        {/* AP List */}
        {expanded && (
          <div className="border-t border-gray-100 pt-2 -mx-2">
            {loadingAPs ? (
              <div className="flex items-center justify-center py-4">
                <RefreshCw className="h-4 w-4 animate-spin text-[var(--brand)]" />
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

        {/* Auto-reboot history */}
        {isSuperuser && sw.vendor === "cisco" && sw.ap_vlan === 20 && (
          <button
            onClick={() => setHistoryExpanded(!historyExpanded)}
            className="flex items-center gap-1.5 text-xs font-medium text-[var(--brand)] hover:text-[var(--brand-strong)] transition"
          >
            <History className="h-3.5 w-3.5" />
            История автоперезагрузок
            {historyExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
        )}
        {historyExpanded && (
          <div className="border-t border-gray-100 pt-2 -mx-2">
            {loadingHistory ? (
              <div className="flex items-center justify-center py-4">
                <RefreshCw className="h-4 w-4 animate-spin text-[var(--brand)]" />
                <span className="ml-2 text-xs text-gray-400">Загрузка...</span>
              </div>
            ) : history && history.length > 0 ? (
              <div className="space-y-0.5 max-h-64 overflow-y-auto">
                {history.map((entry, i) => (
                  <div key={i} className={`flex items-start gap-2 py-1.5 px-3 rounded-lg text-[11px] ${entry.severity === "error" ? "text-[var(--danger-fg)]" : "text-gray-600"}`}>
                    <span className="font-mono text-gray-400 shrink-0">
                      {new Date(entry.created_at).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })}
                    </span>
                    <span>{entry.message}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-xs text-gray-400 text-center py-3">Событий пока нет</div>
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
              className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-[var(--brand)] transition disabled:opacity-40"
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
