import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  RefreshCw, Pencil, Trash2, Monitor, Music, ExternalLink, Clock, Cpu,
  Network, Wifi, Play, Square, Volume2, Upload, X, FileAudio, Copy, MoreHorizontal, Radio,
} from "lucide-react";
import type { MediaAssignment, MediaClientHeartbeat, MediaPlayer } from "../client";
import {
  getIconbitStatus, iconbitPlay, iconbitStop,
  iconbitPlayFile, iconbitDeleteFile, iconbitUpload,
} from "../client";

interface Props {
  player: MediaPlayer;
  onPoll: (id: string) => void;
  onEdit: (player: MediaPlayer) => void;
  onDelete: (id: string) => void;
  onManageMedia: (player: MediaPlayer) => void;
  isPolling: boolean;
  isSuperuser: boolean;
  mediaAssignment?: MediaAssignment;
  mediaHeartbeat?: MediaClientHeartbeat;
}

const DEVICE_STYLES: Record<string, { bg: string; iconBg: string; iconColor: string; icon: typeof Monitor }> = {
  nettop: { bg: "bg-rose-50", iconBg: "bg-rose-50", iconColor: "text-rose-600", icon: Monitor },
  iconbit: { bg: "bg-rose-50", iconBg: "bg-rose-50", iconColor: "text-rose-600", icon: Music },
  twix: { bg: "bg-rose-50", iconBg: "bg-rose-50", iconColor: "text-rose-600", icon: Music },
};

const DEVICE_LABELS: Record<string, string> = {
  nettop: "Неттоп",
  iconbit: "Iconbit",
  twix: "Twix",
};

function statusBadge(player: MediaPlayer) {
  if (player.is_online === null) {
    return <span className="inline-flex items-center gap-1 text-xs text-gray-400"><span className="h-2 w-2 rounded-full bg-gray-300" />Не проверен</span>;
  }
  if (player.is_online) {
    return <span className="inline-flex items-center gap-1 text-xs text-emerald-600"><span className="h-2 w-2 rounded-full bg-emerald-500" />Онлайн</span>;
  }
  return <span className="inline-flex items-center gap-1 text-xs text-red-500"><span className="h-2 w-2 rounded-full bg-red-500" />Оффлайн</span>;
}

function webPanelUrl(player: MediaPlayer): string {
  if (player.device_type === "iconbit") return `http://${player.ip_address}:8081`;
  return `http://${player.ip_address}`;
}

function IconbitControls({ playerId }: { playerId: string }) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: ibStatus, refetch } = useQuery({
    queryKey: ["iconbit-status", playerId],
    queryFn: () => getIconbitStatus(playerId),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const withBusy = (fn: () => Promise<unknown>) => async () => {
    setBusy(true);
    try { await fn(); } finally {
      setBusy(false);
      refetch();
    }
  };

  const playMut = useMutation({ mutationFn: () => iconbitPlay(playerId) });
  const stopMut = useMutation({ mutationFn: () => iconbitStop(playerId) });

  const playFileMut = useMutation({
    mutationFn: (filename: string) => iconbitPlayFile(playerId, filename),
    onSettled: () => refetch(),
  });

  const deleteFileMut = useMutation({
    mutationFn: (filename: string) => iconbitDeleteFile(playerId, filename),
    onSettled: () => refetch(),
  });

  const uploadMut = useMutation({
    mutationFn: (file: File) => iconbitUpload(playerId, file),
    onSettled: () => refetch(),
  });

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadMut.mutate(file);
    e.target.value = "";
  };

  if (!ibStatus) return null;

  const fmtTime = (sec: number | null) => {
    if (sec == null || sec <= 0) return null;
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    return h > 0
      ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
      : `${m}:${String(s).padStart(2, "0")}`;
  };

  const posStr = fmtTime(ibStatus.position);
  const durStr = fmtTime(ibStatus.duration);
  const hasProgress = ibStatus.duration != null && ibStatus.duration > 0 && ibStatus.position != null;
  const progress = hasProgress
    ? Math.min(100, ((ibStatus.position ?? 0) / (ibStatus.duration ?? 1)) * 100)
    : null;

  const stateLabel = ibStatus.state === "paused" ? "На паузе" : null;
  const isPlaying = ibStatus.is_playing && ibStatus.now_playing;

  return (
    <div className="mt-1 space-y-2">
      {/* Now playing */}
      <div className="space-y-1">
        <div className="flex items-center gap-1.5 text-xs">
          {isPlaying ? (
            <div className="flex items-end gap-[2px] h-3 w-3 shrink-0" title="Воспроизводится">
              <span className="w-[3px] bg-rose-500 rounded-sm animate-eq1" />
              <span className="w-[3px] bg-rose-500 rounded-sm animate-eq2" />
              <span className="w-[3px] bg-rose-500 rounded-sm animate-eq3" />
            </div>
          ) : (
            <Volume2 className="h-3 w-3 text-gray-300 shrink-0" />
          )}
          {isPlaying ? (
            <span className="text-rose-700 font-medium truncate" title={ibStatus.now_playing!}>
              {ibStatus.now_playing!.length > 35 ? ibStatus.now_playing!.slice(0, 35) + "..." : ibStatus.now_playing}
            </span>
          ) : (
            <span className="text-gray-400 italic">Не воспроизводится</span>
          )}
          {stateLabel && <span className="text-[10px] text-amber-600 bg-amber-50 px-1 py-0.5 rounded">{stateLabel}</span>}
        </div>
        {/* Progress bar — real progress or animated placeholder */}
        {isPlaying && (
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1 bg-gray-200 rounded-full overflow-hidden">
              {progress != null ? (
                <div className="h-full bg-rose-500 rounded-full transition-all" style={{ width: `${progress}%` }} />
              ) : (
                <div className="h-full bg-rose-400 rounded-full animate-progress-sweep" />
              )}
            </div>
            {posStr && durStr ? (
              <span className="text-[10px] text-gray-400 shrink-0">{posStr} / {durStr}</span>
            ) : (
              <span className="text-[10px] text-rose-400 shrink-0">играет</span>
            )}
          </div>
        )}
      </div>

      {/* Play / Stop / Upload buttons */}
      <div className="flex items-center gap-1 flex-wrap">
        <button
          onClick={withBusy(() => playMut.mutateAsync())}
          disabled={busy}
          className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-40 transition"
          title="Воспроизвести"
        >
          <Play className="h-3 w-3" /> Play
        </button>
        <button
          onClick={withBusy(() => stopMut.mutateAsync())}
          disabled={busy}
          className="inline-flex items-center gap-1 rounded-md bg-red-50 px-2 py-1 text-[11px] font-medium text-red-600 hover:bg-red-100 disabled:opacity-40 transition"
          title="Остановить"
        >
          <Square className="h-3 w-3" /> Stop
        </button>
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={busy || uploadMut.isPending}
          className="inline-flex items-center gap-1 rounded-md bg-rose-50 px-2 py-1 text-[11px] font-medium text-rose-700 hover:bg-rose-100 disabled:opacity-40 transition"
          title="Загрузить файл"
        >
          <Upload className="h-3 w-3" /> {uploadMut.isPending ? "..." : "Загрузить"}
        </button>
        <input ref={fileInputRef} type="file" accept="audio/*,video/*" className="hidden" onChange={handleUpload} />
        {ibStatus.free_space && (
          <span className="text-[10px] text-gray-400 ml-auto">{ibStatus.free_space}</span>
        )}
      </div>

      {/* File list */}
      {ibStatus.files.length > 0 && (
        <div className="space-y-1">
          {ibStatus.files.map((f) => (
            <div key={f} className="flex items-center gap-1.5 text-[11px] group">
              <FileAudio className="h-3 w-3 text-gray-400 shrink-0" />
              <span
                className="text-gray-600 truncate cursor-pointer hover:text-rose-700 transition flex-1"
                title={`Воспроизвести: ${f}`}
                onClick={() => playFileMut.mutate(f)}
              >
                {f}
              </span>
              <button
                onClick={() => { if (confirm(`Удалить ${f}?`)) deleteFileMut.mutate(f); }}
                className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-500 transition"
                title="Удалить файл"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function MediaPlayerCard({
  player,
  onPoll,
  onEdit,
  onDelete,
  onManageMedia,
  isPolling,
  isSuperuser,
  mediaAssignment,
  mediaHeartbeat,
}: Props) {
  const [isActionsOpen, setIsActionsOpen] = useState(false);
  const [copiedDeviceId, setCopiedDeviceId] = useState(false);
  const style = DEVICE_STYLES[player.device_type] ?? DEVICE_STYLES.nettop;
  const Icon = style.icon;
  const deviceLabel = DEVICE_LABELS[player.device_type] ?? player.device_type;
  const isIconbit = player.device_type === "iconbit";
  const isNettop = player.device_type === "nettop";

  const polledAt = player.last_polled_at
    ? new Date(player.last_polled_at).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })
    : null;

  const ports = player.open_ports?.split(",").filter(Boolean) ?? [];
  const netSupportTarget = (player.hostname || "").trim();
  const showMediaStatus = isNettop || Boolean(mediaAssignment);

  const copyNetSupportTarget = async () => {
    if (!netSupportTarget || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(netSupportTarget);
    } catch {
      // Ignore clipboard errors in unsupported environments.
    }
  };

  const copyDeviceId = async () => {
    if (!navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(player.id);
      setCopiedDeviceId(true);
      window.setTimeout(() => setCopiedDeviceId(false), 1600);
    } catch {
      // Ignore clipboard errors in unsupported environments.
    }
  };

  return (
    <div className={`app-panel app-card rounded-xl border shadow-sm hover:shadow-md transition flex flex-col ${isActionsOpen ? "z-30" : "z-0"}`}>
      <div className="p-5 flex flex-col gap-3">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className={`rounded-lg ${style.iconBg} p-2`}>
              <Icon className={`h-5 w-5 ${style.iconColor}`} />
            </div>
            <div>
              <div className="font-medium text-sm text-gray-900">{player.name}</div>
              <div className="text-xs text-gray-500">{player.model}</div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            {statusBadge(player)}
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${style.bg} ${style.iconColor}`}>
              {deviceLabel}
            </span>
          </div>
        </div>

        {/* Device info */}
        <div className="space-y-1.5">
          {showMediaStatus && (
            <button
              type="button"
              onClick={() => onManageMedia(player)}
              className="flex w-full items-center gap-2 rounded-lg border border-gray-100 bg-gray-50 px-2.5 py-2 text-left text-xs transition hover:border-rose-200 hover:bg-rose-50"
              title="Настроить централизованное медиа"
            >
              <Radio className={`size-3.5 ${mediaHeartbeat?.player_state === "playing" ? "text-emerald-600" : "text-gray-400"}`} />
              <span className="min-w-0 flex-1 truncate text-gray-700">
                {mediaAssignment?.title || "Медиа не назначено"}
              </span>
              {mediaAssignment && (
                <span className="shrink-0 rounded bg-white px-1.5 py-0.5 text-[10px] text-gray-500">
                  {mediaAssignment.media_type}
                </span>
              )}
            </button>
          )}

          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <Wifi className="h-3 w-3 text-gray-400" />
            <span className="font-mono">{player.ip_address}</span>
          </div>

          {isNettop && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Radio className="h-3 w-3 text-gray-400" />
              <span className="font-mono truncate" title={player.id}>
                ID: {player.id}
              </span>
              <button
                type="button"
                onClick={copyDeviceId}
                className="inline-flex items-center rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-rose-600 transition"
                title="Скопировать UUID для Windows-клиента"
                aria-label="Скопировать UUID устройства"
              >
                <Copy className="h-3 w-3" />
              </button>
              {copiedDeviceId && <span className="text-[10px] text-emerald-600">скопировано</span>}
            </div>
          )}

          {player.mac_address && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Network className="h-3 w-3 text-gray-400" />
              <span className="font-mono">{player.mac_address}</span>
            </div>
          )}

          {player.hostname && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Monitor className="h-3 w-3 text-gray-400" />
              <span>{player.hostname}</span>
              {isNettop && netSupportTarget && (
                <button
                  onClick={copyNetSupportTarget}
                  className="inline-flex items-center rounded p-0.5 text-gray-400 hover:text-rose-600 hover:bg-gray-100 transition"
                  title="Скопировать hostname для NetSupport"
                >
                  <Copy className="h-3 w-3" />
                </button>
              )}
            </div>
          )}

          {player.os_info && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Cpu className="h-3 w-3 text-gray-400" />
              <span className="truncate" title={player.os_info}>
                {player.os_info.length > 60 ? player.os_info.slice(0, 60) + "..." : player.os_info}
              </span>
            </div>
          )}

          {player.uptime && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Clock className="h-3 w-3 text-gray-400" />
              <span>Uptime: {player.uptime}</span>
            </div>
          )}

          {ports.length > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500 flex-wrap">
              <span className="text-gray-400">Порты:</span>
              {ports.map((p) => (
                <span key={p} className="bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded text-[10px] font-mono">
                  {p}
                </span>
              ))}
            </div>
          )}

          {isIconbit && player.is_online && <IconbitControls playerId={player.id} />}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between pt-2 border-t border-gray-100">
          <span className="text-[11px] text-gray-400">
            {polledAt ? `Обновлено: ${polledAt}` : "Ещё не опрашивался"}
          </span>
          <div className="relative flex items-center gap-1">
            <button
              onClick={() => onPoll(player.id)}
              disabled={isPolling}
              className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-rose-600 transition disabled:opacity-40"
              title="Опросить"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isPolling ? "animate-spin" : ""}`} />
            </button>
            {isNettop ? (
              <button
                onClick={copyNetSupportTarget}
                disabled={!netSupportTarget}
                className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-rose-600 transition disabled:opacity-40"
                title={netSupportTarget ? "Скопировать hostname для ручного подключения" : "Заполните hostname для подключения"}
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            ) : (
              <a
                href={webPanelUrl(player)}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-rose-600 transition"
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
                  <div className="absolute right-0 top-8 z-50 app-panel min-w-[160px] p-1.5">
                    <button
                      type="button"
                      onClick={() => { setIsActionsOpen(false); onManageMedia(player); }}
                      className="w-full inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-100 transition"
                    >
                      <Radio className="h-3.5 w-3.5" />
                      Медиа
                    </button>
                    <button
                      onClick={() => { setIsActionsOpen(false); onEdit(player); }}
                      className="w-full inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-100 transition"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      Редактировать
                    </button>
                    <button
                      onClick={() => { setIsActionsOpen(false); onDelete(player.id); }}
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
