import { useState, useRef } from "react";
import { keepPreviousData, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Plus, Search, Monitor, Music, Play, Square, Upload, Replace } from "lucide-react";
import {
  getMediaPlayers,
  pollAllMediaPlayers,
  pollMediaPlayer,
  createMediaPlayer,
  updateMediaPlayer,
  deleteMediaPlayer,
  getMediaAssignments,
  getMediaAssets,
  getMediaClientHeartbeats,
  iconbitBulkPlay,
  iconbitBulkStop,
  iconbitBulkUpload,
  iconbitBulkReplace,
  setMediaAssignment,
  uploadMediaAsset,
  type MediaPlayer,
  type DeviceType,
  type MediaAssignmentPayload,
} from "../client";
import { useAuth } from "../auth";
import MediaPlayerCard from "../components/MediaPlayerCard";
import MediaPlayerForm from "../components/MediaPlayerForm";
import MediaAssignmentPanel from "../components/MediaAssignmentPanel";
import { useEntityAutoPoll } from "../hooks/useEntityAutoPoll";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useConfirm } from "../components/ConfirmDialog";

type FilterKey = "all" | DeviceType;
type StatusFilter = "all" | "online" | "offline";

const FILTERS: { key: FilterKey; label: string; icon: typeof Monitor }[] = [
  { key: "all", label: "Все", icon: Monitor },
  { key: "nettop", label: "Неттопы", icon: Monitor },
  { key: "iconbit", label: "Iconbit", icon: Music },
  { key: "twix", label: "Twix", icon: Music },
];

export default function MediaPlayersPage() {
  const { user } = useAuth();
  const isSuperuser = user?.is_superuser ?? false;
  const queryClient = useQueryClient();
  const confirm = useConfirm();

  const [activeFilter, setActiveFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [showForm, setShowForm] = useState(false);
  const [editingPlayer, setEditingPlayer] = useState<MediaPlayer | null>(null);
  const [pollingIds, setPollingIds] = useState<Set<string>>(new Set());
  const [formError, setFormError] = useState<string | null>(null);
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [mediaTarget, setMediaTarget] = useState<MediaPlayer | null>(null);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const bulkFileRef = useRef<HTMLInputElement>(null);
  const replaceFileRef = useRef<HTMLInputElement>(null);

  const deviceTypeParam = activeFilter === "all" ? undefined : activeFilter;
  const showIconbitBulk = activeFilter === "iconbit";

  const { data, isLoading } = useQuery({
    queryKey: ["media-players", deviceTypeParam, debouncedSearch],
    queryFn: () => getMediaPlayers(debouncedSearch || undefined, deviceTypeParam),
    placeholderData: keepPreviousData,
  });

  const { data: mediaAssignments } = useQuery({
    queryKey: ["media-center", "assignments"],
    queryFn: getMediaAssignments,
    staleTime: 15_000,
  });

  const { data: mediaHeartbeats } = useQuery({
    queryKey: ["media-center", "heartbeats"],
    queryFn: getMediaClientHeartbeats,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

  const { data: mediaAssets } = useQuery({
    queryKey: ["media-center", "assets"],
    queryFn: getMediaAssets,
    staleTime: 15_000,
  });

  const pollAllMut = useMutation({
    mutationFn: () => pollAllMediaPlayers(deviceTypeParam),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["media-players"] }),
  });

  // Real device polling now runs on a schedule in the backend (Celery Beat),
  // so this no longer triggers a real poll from every open tab - it just
  // refreshes from cache. Realtime updates arrive via WebSocket regardless.
  useEntityAutoPoll({
    enabled: !showForm,
    queryKeyRoot: "media-players",
    poll: () => Promise.resolve(),
  });

  const pollOneMut = useMutation({
    mutationFn: pollMediaPlayer,
    onMutate: (id) => setPollingIds((s) => new Set(s).add(id)),
    onSettled: (_d, _e, id) => {
      setPollingIds((s) => { const n = new Set(s); n.delete(id); return n; });
      queryClient.invalidateQueries({ queryKey: ["media-players"] });
    },
  });

  const extractError = (err: unknown): string => {
    if (err && typeof err === "object" && "response" in err) {
      const resp = (err as { response?: { data?: { detail?: string }; status?: number } }).response;
      const detail = resp?.data?.detail;
      if (detail === "Device with this IP already exists") return "Устройство с таким IP уже существует";
      if (resp?.status === 409) return "Устройство с таким IP уже существует";
      if (detail) return detail;
    }
    return "Не удалось сохранить устройство";
  };

  const createMut = useMutation({
    mutationFn: createMediaPlayer,
    onSuccess: () => {
      setFormError(null);
      queryClient.invalidateQueries({ queryKey: ["media-players"] });
      setShowForm(false);
    },
    onError: (err) => setFormError(extractError(err)),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, ...rest }: { id: string; [key: string]: unknown }) =>
      updateMediaPlayer(id, rest),
    onSuccess: () => {
      setFormError(null);
      queryClient.invalidateQueries({ queryKey: ["media-players"] });
      setEditingPlayer(null);
      setShowForm(false);
    },
    onError: (err) => setFormError(extractError(err)),
  });

  const deleteMut = useMutation({
    mutationFn: deleteMediaPlayer,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["media-players"] }),
  });

  const mediaSaveMut = useMutation({
    mutationFn: ({ playerId, payload }: { playerId: string; payload: MediaAssignmentPayload }) =>
      setMediaAssignment(playerId, payload),
    onSuccess: () => {
      setMediaError(null);
      setMediaTarget(null);
      queryClient.invalidateQueries({ queryKey: ["media-center"] });
    },
    onError: (err) => setMediaError(extractError(err)),
  });

  const mediaUploadMut = useMutation({
    mutationFn: (file: File) => uploadMediaAsset(file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["media-center", "assets"] }),
    onError: (err) => setMediaError(extractError(err)),
  });

  const handleDelete = async (id: string) => {
    if (await confirm("Удалить устройство?", { danger: true, confirmText: "Удалить" })) deleteMut.mutate(id);
  };

  const showBulkResult = (res: { success: number; failed: number }) => {
    setBulkMsg(`Успешно: ${res.success}, ошибок: ${res.failed}`);
    setTimeout(() => setBulkMsg(null), 4000);
    queryClient.invalidateQueries({ queryKey: ["iconbit-status"] });
  };

  const bulkPlayMut = useMutation({
    mutationFn: iconbitBulkPlay,
    onSuccess: showBulkResult,
  });

  const bulkStopMut = useMutation({
    mutationFn: iconbitBulkStop,
    onSuccess: showBulkResult,
  });

  const bulkUploadMut = useMutation({
    mutationFn: iconbitBulkUpload,
    onSuccess: (res) => {
      showBulkResult(res);
      queryClient.invalidateQueries({ queryKey: ["iconbit-status"] });
    },
  });

  const bulkReplaceMut = useMutation({
    mutationFn: iconbitBulkReplace,
    onSuccess: (res) => {
      showBulkResult(res);
      queryClient.invalidateQueries({ queryKey: ["iconbit-status"] });
    },
  });

  const handleBulkUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) bulkUploadMut.mutate(file);
    e.target.value = "";
  };

  const handleBulkReplace = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && await confirm(`Заменить плейлист на всех Iconbit на "${file.name}"?\nСтарые файлы будут удалены.`, { danger: true, confirmText: "Заменить" })) {
      bulkReplaceMut.mutate(file);
    }
    e.target.value = "";
  };

  const players = data?.data ?? [];
  const assignmentByPlayer = new Map((mediaAssignments?.data ?? []).map((row) => [row.player_id, row]));
  const heartbeatByPlayer = new Map((mediaHeartbeats?.data ?? []).map((row) => [row.player_id, row]));
  const sortedPlayers = [...players].sort((a, b) => {
    const rank = (value: boolean | null) => (value === true ? 0 : value === null ? 1 : 2);
    return rank(a.is_online) - rank(b.is_online);
  });
  const visiblePlayers = sortedPlayers.filter((player) => {
    if (statusFilter === "online") return player.is_online === true;
    if (statusFilter === "offline") return player.is_online === false;
    return true;
  });
  const total = players.length;
  const online = players.filter((p) => p.is_online === true).length;
  const offline = players.filter((p) => p.is_online === false).length;
  const bulkBusy = bulkPlayMut.isPending || bulkStopMut.isPending || bulkUploadMut.isPending || bulkReplaceMut.isPending;

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
              placeholder="Умный поиск: имя, hostname, IP, модель (A/А)"
              className="app-input w-full pl-10 pr-4 py-2 text-sm"
            />
          </div>
          <div className="app-toolbar-actions flex flex-wrap gap-2">
            <button
              onClick={() => pollAllMut.mutate()}
              disabled={pollAllMut.isPending}
              className="app-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50 transition"
            >
              <RefreshCw className={`h-4 w-4 ${pollAllMut.isPending ? "animate-spin" : ""}`} />
              {pollAllMut.isPending ? "Опрос..." : "Опросить все"}
            </button>
            {isSuperuser && (
              <button
                onClick={() => { setEditingPlayer(null); setFormError(null); setShowForm(true); }}
                className="app-btn-secondary inline-flex items-center gap-2 px-4 py-2 text-sm transition"
              >
                <Plus className="h-4 w-4" />
                Добавить
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid gap-4 grid-cols-3">
        <Stat label="Всего" value={total} color="text-gray-900" bg="bg-gray-100" isActive={statusFilter === "all"} onClick={() => setStatusFilter("all")} />
        <Stat label="Онлайн" value={online} color="text-emerald-700" bg="bg-emerald-50" isActive={statusFilter === "online"} onClick={() => setStatusFilter("online")} />
        <Stat label="Оффлайн" value={offline} color="text-red-700" bg="bg-red-50" isActive={statusFilter === "offline"} onClick={() => setStatusFilter("offline")} />
      </div>

      {/* Filter tabs */}
      <div className="app-tabbar flex gap-1 p-1.5 w-fit max-w-full overflow-x-auto app-compact-scroll">
        {FILTERS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setActiveFilter(key)}
            className={`app-tab inline-flex items-center gap-2 px-4 py-2 text-sm font-medium ${
              activeFilter === key
                ? "active"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Iconbit bulk controls */}
      {showIconbitBulk && (
        <div className="app-panel p-4 space-y-3">
          <div className="text-sm font-semibold text-rose-800">Управление всеми Iconbit</div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => replaceFileRef.current?.click()}
              disabled={bulkBusy}
              className="app-btn-primary inline-flex items-center gap-1.5 px-4 py-2 text-sm disabled:opacity-40 transition"
            >
              <Replace className="h-4 w-4" /> {bulkReplaceMut.isPending ? "Замена..." : "Заменить плейлист на всех"}
            </button>
            <input ref={replaceFileRef} type="file" accept="audio/*,video/*" className="hidden" onChange={handleBulkReplace} />
            <button
              onClick={() => bulkPlayMut.mutate()}
              disabled={bulkBusy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-40 transition"
            >
              <Play className="h-3.5 w-3.5" /> Play все
            </button>
            <button
              onClick={() => bulkStopMut.mutate()}
              disabled={bulkBusy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-red-50 border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-100 disabled:opacity-40 transition"
            >
              <Square className="h-3.5 w-3.5" /> Stop все
            </button>
            <button
              onClick={() => bulkFileRef.current?.click()}
              disabled={bulkBusy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-rose-50 border border-rose-200 px-3 py-1.5 text-sm font-medium text-rose-700 hover:bg-rose-100 disabled:opacity-40 transition"
            >
              <Upload className="h-3.5 w-3.5" /> {bulkUploadMut.isPending ? "..." : "Добавить файл на все"}
            </button>
            <input ref={bulkFileRef} type="file" accept="audio/*,video/*" className="hidden" onChange={handleBulkUpload} />
          </div>
          {bulkMsg && (
            <div className="text-sm text-rose-700 bg-rose-100 rounded-lg px-3 py-1.5 w-fit">{bulkMsg}</div>
          )}
        </div>
      )}

      {/* Grid */}
      {isLoading ? (
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
              <div className="app-skeleton h-20 w-full" />
              <div className="app-skeleton h-8 w-1/2" />
            </div>
          ))}
        </div>
      ) : visiblePlayers.length === 0 ? (
        <div className="app-empty text-center py-16 text-gray-400">
          <p className="text-lg">Нет устройств</p>
          <p className="text-sm mt-1">Добавьте первое устройство для мониторинга</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {visiblePlayers.map((player) => (
            <MediaPlayerCard
              key={player.id}
              player={player}
              onPoll={(id) => pollOneMut.mutate(id)}
              onEdit={(p) => { setEditingPlayer(p); setFormError(null); setShowForm(true); }}
              onDelete={handleDelete}
              onManageMedia={(p) => { setMediaTarget(p); setMediaError(null); }}
              isPolling={pollingIds.has(player.id) || pollAllMut.isPending}
              isSuperuser={isSuperuser}
              mediaAssignment={assignmentByPlayer.get(player.id)}
              mediaHeartbeat={heartbeatByPlayer.get(player.id)}
            />
          ))}
        </div>
      )}

      {/* Modal form */}
      {showForm && (
        <MediaPlayerForm
          player={editingPlayer}
          loading={createMut.isPending || updateMut.isPending}
          error={formError}
          onClose={() => { setShowForm(false); setEditingPlayer(null); setFormError(null); }}
          onSave={(formData) => {
            setFormError(null);
            if (editingPlayer) {
              updateMut.mutate({ id: editingPlayer.id, ...formData });
            } else {
              createMut.mutate(formData);
            }
          }}
        />
      )}

      {mediaTarget && (
        <MediaAssignmentPanel
          player={mediaTarget}
          assignment={assignmentByPlayer.get(mediaTarget.id)}
          heartbeat={heartbeatByPlayer.get(mediaTarget.id)}
          assets={mediaAssets?.data ?? []}
          saving={mediaSaveMut.isPending}
          uploading={mediaUploadMut.isPending}
          error={mediaError}
          onClose={() => { setMediaTarget(null); setMediaError(null); }}
          onSave={(payload) => mediaSaveMut.mutate({ playerId: mediaTarget.id, payload })}
          onUpload={(file) => mediaUploadMut.mutateAsync(file)}
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
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`app-stat ${bg} w-full px-4 py-3 text-left transition ${isActive ? "ring-2 ring-rose-400/50" : "hover:-translate-y-0.5 hover:shadow-md"}`}
    >
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </button>
  );
}
