import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, Film, Music, Radio, Save, Upload, X } from "lucide-react";
import type {
  MediaAssignment,
  MediaAssignmentPayload,
  MediaAsset,
  MediaClientHeartbeat,
  MediaKind,
  MediaPlayer,
  PlaybackMode,
} from "../client";

interface Props {
  player: MediaPlayer;
  assignment?: MediaAssignment;
  heartbeat?: MediaClientHeartbeat;
  assets?: MediaAsset[];
  saving: boolean;
  uploading?: boolean;
  error?: string | null;
  onClose: () => void;
  onSave: (payload: MediaAssignmentPayload) => void;
  onUpload?: (file: File) => Promise<MediaAsset>;
}

const MEDIA_TYPES: { value: MediaKind; label: string; icon: typeof Radio }[] = [
  { value: "stream", label: "Поток", icon: Radio },
  { value: "video", label: "Видео", icon: Film },
  { value: "audio", label: "Аудио", icon: Music },
];

const PLAYBACK_MODES: { value: PlaybackMode; label: string }[] = [
  { value: "loop", label: "Повтор" },
  { value: "once", label: "Один раз" },
  { value: "scheduled", label: "По расписанию" },
];

function normalizeVolume(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function heartbeatLabel(heartbeat?: MediaClientHeartbeat): string {
  if (!heartbeat) return "Агент ещё не выходил на связь";
  const seen = new Date(heartbeat.last_seen_at).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  if (heartbeat.player_state === "playing") return `Воспроизводит, связь ${seen}`;
  if (heartbeat.player_state === "error") return `Ошибка агента, связь ${seen}`;
  if (heartbeat.player_state === "disabled") return `Остановлен назначением, связь ${seen}`;
  return `Состояние: ${heartbeat.player_state}, связь ${seen}`;
}

function formatBytes(value: number | null): string {
  if (!value || value <= 0) return "";
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} КБ`;
  return `${(value / 1024 / 1024).toFixed(1)} МБ`;
}

export default function MediaAssignmentPanel({
  player,
  assignment,
  heartbeat,
  assets = [],
  saving,
  uploading = false,
  error,
  onClose,
  onSave,
  onUpload,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [mediaType, setMediaType] = useState<MediaKind>("stream");
  const [sourceUrl, setSourceUrl] = useState("");
  const [assetId, setAssetId] = useState<string>("");
  const [playbackMode, setPlaybackMode] = useState<PlaybackMode>("loop");
  const [volume, setVolume] = useState("");
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    setTitle(assignment?.title || player.name);
    setMediaType((assignment?.media_type as MediaKind | undefined) || "stream");
    setSourceUrl(assignment?.source_url || "");
    setAssetId(assignment?.asset_id || "");
    setPlaybackMode((assignment?.playback_mode as PlaybackMode | undefined) || "loop");
    setVolume(assignment?.volume == null ? "" : String(assignment.volume));
    setEnabled(assignment?.enabled ?? true);
  }, [assignment, player.name, player.id]);

  const formReady = useMemo(() => title.trim() !== "" && sourceUrl.trim() !== "", [title, sourceUrl]);
  const revisionMismatch =
    assignment && heartbeat?.current_revision != null && heartbeat.current_revision !== assignment.revision;

  const copyDeviceId = async () => {
    if (!navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(player.id);
    } catch {
      // Ignore clipboard errors in unsupported environments.
    }
  };

  const applyAsset = (asset: MediaAsset) => {
    setAssetId(asset.id);
    setTitle(asset.title);
    setMediaType(asset.media_type as MediaKind);
    setSourceUrl(asset.source_url);
  };

  const handleAssetSelect = (value: string) => {
    setAssetId(value);
    const asset = assets.find((row) => row.id === value);
    if (asset) applyAsset(asset);
  };

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !onUpload) return;
    try {
      const asset = await onUpload(file);
      applyAsset(asset);
    } catch {
      // Error is rendered by the parent mutation handler.
    }
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!formReady || saving) return;
    onSave({
      title: title.trim(),
      media_type: mediaType,
      source_url: sourceUrl.trim(),
      asset_id: assetId || null,
      playback_mode: playbackMode,
      volume: normalizeVolume(volume),
      enabled,
    });
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 px-4 py-6">
      <form onSubmit={submit} className="app-panel w-full max-w-2xl max-h-[calc(100dvh-3rem)] overflow-y-auto p-5">
        <div className="flex items-start justify-between gap-4 border-b border-gray-100 pb-4">
          <div>
            <div className="text-xs font-medium uppercase text-gray-400">Медиа для устройства</div>
            <h2 className="mt-1 text-xl font-semibold text-gray-900 text-balance">{player.name}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
              <span className="font-mono">{player.ip_address}</span>
              <button
                type="button"
                onClick={copyDeviceId}
                className="inline-flex max-w-full items-center gap-1 rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-600 hover:bg-gray-200"
                title="Скопировать UUID для Windows-клиента"
              >
                ID: <span className="truncate">{player.id}</span>
              </button>
              {assignment && <span>ревизия {assignment.revision}</span>}
              {revisionMismatch && <span className="text-amber-700">агент ещё не применил изменение</span>}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
            aria-label="Закрыть"
          >
            <X className="size-5" />
          </button>
        </div>

        <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
          <div className="flex items-center gap-2 text-sm text-gray-700">
            <Activity className="size-4 text-gray-500" />
            <span>{heartbeatLabel(heartbeat)}</span>
          </div>
          {heartbeat?.error_message && (
            <div className="mt-1 text-xs text-rose-700 text-pretty">{heartbeat.error_message}</div>
          )}
        </div>

        <div className="mt-5 grid gap-4">
          <label className="grid gap-1.5 text-sm font-medium text-gray-700">
            Название
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="app-input px-3 py-2 text-sm"
              placeholder="Экран центрального зала"
            />
          </label>

          <div className="grid gap-2 rounded-lg border border-gray-200 bg-gray-50 p-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm font-medium text-gray-700">Файл из медиатеки</div>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={!onUpload || uploading}
                className="app-btn-secondary inline-flex w-fit items-center gap-2 px-3 py-1.5 text-sm disabled:opacity-50"
              >
                <Upload className="size-4" />
                {uploading ? "Загрузка..." : "Загрузить файл"}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="audio/*,video/*,.mp3,.wav,.flac,.aac,.ogg,.mp4,.mkv,.mov,.avi,.webm"
                className="hidden"
                onChange={handleUpload}
              />
            </div>
            <select
              aria-label="Файл из медиатеки"
              value={assetId}
              onChange={(event) => handleAssetSelect(event.target.value)}
              className="app-input px-3 py-2 text-sm"
            >
              <option value="">Не выбран, используется URL ниже</option>
              {assets.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {asset.title}
                  {asset.original_filename ? ` (${asset.original_filename})` : ""}
                  {asset.file_size_bytes ? `, ${formatBytes(asset.file_size_bytes)}` : ""}
                </option>
              ))}
            </select>
          </div>

          <div className="grid gap-2">
            <div className="text-sm font-medium text-gray-700">Тип</div>
            <div className="app-tabbar flex w-fit max-w-full gap-1 overflow-x-auto p-1">
              {MEDIA_TYPES.map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setMediaType(value)}
                  className={`app-tab inline-flex items-center gap-2 px-3 py-2 text-sm ${
                    mediaType === value ? "active" : "text-gray-500 hover:text-gray-800"
                  }`}
                >
                  <Icon className="size-4" />
                  {label}
                </button>
              ))}
            </div>
          </div>

          <label className="grid gap-1.5 text-sm font-medium text-gray-700">
            URL или путь
            <input
              value={sourceUrl}
              onChange={(event) => setSourceUrl(event.target.value)}
              className="app-input px-3 py-2 text-sm"
              placeholder="http://media.local/live/main.m3u8"
            />
          </label>

          <div className="grid gap-4 md:grid-cols-[1fr_140px]">
            <label className="grid gap-1.5 text-sm font-medium text-gray-700">
              Режим
              <select
                value={playbackMode}
                onChange={(event) => setPlaybackMode(event.target.value as PlaybackMode)}
                className="app-input px-3 py-2 text-sm"
              >
                {PLAYBACK_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-gray-700">
              Громкость
              <input
                value={volume}
                onChange={(event) => setVolume(event.target.value)}
                inputMode="numeric"
                className="app-input px-3 py-2 text-sm tabular-nums"
                placeholder="0-100"
              />
            </label>
          </div>

          <label className="flex items-center gap-3 rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
              className="size-4 accent-rose-600"
            />
            Включено для агента
          </label>

          {error && <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
        </div>

        <div className="mt-5 flex items-center justify-end gap-2 border-t border-gray-100 pt-4">
          <button type="button" onClick={onClose} className="app-btn-secondary px-4 py-2 text-sm">
            Отмена
          </button>
          <button
            type="submit"
            disabled={!formReady || saving}
            className="app-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50"
          >
            <Save className="size-4" />
            {saving ? "Сохранение..." : "Сохранить"}
          </button>
        </div>
      </form>
    </div>
  );
}
