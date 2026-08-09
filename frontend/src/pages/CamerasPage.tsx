import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, ChevronDown, ChevronUp, Loader2, Power, RefreshCw, Search } from "lucide-react";
import { useAuth } from "../auth";
import { getSwitches, getSwitchCameraPorts, rebootAllCameraPorts } from "../client";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useConfirm } from "../components/ConfirmDialog";
import { showToast } from "../lib/toastBus";
import { apiErrorMessage } from "../lib/apiError";
import CameraPortRow from "../components/CameraPortRow";

export default function CamerasPage() {
  const { user } = useAuth();
  const isSuperuser = user?.is_superuser ?? false;
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["switches", debouncedSearch],
    queryFn: () => getSwitches(debouncedSearch || undefined),
    staleTime: 10_000,
  });

  const cameraSwitches = useMemo(
    () => (data?.data ?? []).filter((sw) => sw.vendor === "cisco").sort((a, b) => a.name.localeCompare(b.name, "ru", { numeric: true })),
    [data],
  );

  return (
    <div className="space-y-6">
      <div className="app-panel p-3">
        <div className="relative w-full md:max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск по магазину"
            className="app-input w-full pl-10 pr-4 py-2 text-sm"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="app-panel p-5">
              <div className="app-skeleton h-6 w-1/3" />
            </div>
          ))}
        </div>
      ) : cameraSwitches.length > 0 ? (
        <div className="space-y-3">
          {cameraSwitches.map((sw) => (
            <CameraSwitchCard
              key={sw.id}
              switchId={sw.id}
              switchName={sw.name}
              isExpanded={expandedId === sw.id}
              onToggle={() => setExpandedId((current) => (current === sw.id ? null : sw.id))}
              isSuperuser={isSuperuser}
            />
          ))}
        </div>
      ) : (
        <div className="app-empty text-center py-16 text-gray-400">
          <Camera className="h-12 w-12 mx-auto mb-3 text-gray-300" />
          <p>Нет свитчей с поддержкой камер</p>
        </div>
      )}
    </div>
  );
}

function CameraSwitchCard({
  switchId,
  switchName,
  isExpanded,
  onToggle,
  isSuperuser,
}: {
  switchId: string;
  switchName: string;
  isExpanded: boolean;
  onToggle: () => void;
  isSuperuser: boolean;
}) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();

  const { data: cameraPorts, isLoading } = useQuery({
    queryKey: ["switch-camera-ports", switchId],
    queryFn: () => getSwitchCameraPorts(switchId),
    enabled: isExpanded,
    staleTime: 30_000,
  });

  const rebootAllMut = useMutation({
    mutationFn: () => rebootAllCameraPorts(switchId),
    onSuccess: (result) => {
      const backOnline = result.back_online_count;
      const message =
        backOnline === undefined
          ? `${switchName}: перезагружено камер — ${result.rebooted_count}`
          : backOnline === result.rebooted_count
            ? `${switchName}: перезагружено и вернулось онлайн — ${backOnline} из ${result.rebooted_count}`
            : `${switchName}: вернулось онлайн ${backOnline} из ${result.rebooted_count} — проверьте остальные на месте`;
      showToast(message, backOnline !== undefined && backOnline < result.rebooted_count ? "error" : "success");
      queryClient.invalidateQueries({ queryKey: ["switch-camera-ports", switchId] });
    },
    onError: (error) => showToast(apiErrorMessage(error, "Не удалось перезагрузить камеры"), "error"),
  });

  const handleRebootAll = async () => {
    const count = cameraPorts?.length ?? 0;
    if (
      await confirm(
        `Перезагрузить все камеры в магазине «${switchName}»?${count ? ` (${count} шт.)` : ""}\n\n` +
          "Камеры перезагружаются по одной, а не все сразу — покрытие видео никогда не пропадает целиком. " +
          "Из-за этого процесс может занять несколько минут.",
        { danger: true, confirmText: "Перезагрузить все" },
      )
    ) {
      rebootAllMut.mutate();
    }
  };

  const downCount = cameraPorts?.filter((cam) => cam.oper_status !== "connected").length ?? 0;

  return (
    <div className="app-panel overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 p-4 text-left hover:bg-gray-50/50 transition"
      >
        <div className="flex items-center gap-3">
          <div className="app-entity-icon">
            <Camera className="h-5 w-5" />
          </div>
          <div>
            <div className="font-medium text-sm text-gray-900">{switchName}</div>
            {isExpanded && cameraPorts && (
              <div className="text-xs text-gray-500">
                {cameraPorts.length} камер{downCount > 0 && <span className="text-red-600"> · {downCount} без связи</span>}
              </div>
            )}
          </div>
        </div>
        {isExpanded ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
      </button>

      {isExpanded && (
        <div className="border-t border-gray-100 p-4 pt-3">
          {isSuperuser && (
            <div className="mb-3 flex justify-end">
              <button
                type="button"
                onClick={handleRebootAll}
                disabled={rebootAllMut.isPending || isLoading || !cameraPorts?.length}
                className="app-btn-secondary inline-flex items-center gap-2 px-3 py-1.5 text-xs disabled:opacity-40"
              >
                {rebootAllMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Power className="h-3.5 w-3.5" />}
                Перезагрузить все камеры
              </button>
            </div>
          )}
          {isLoading ? (
            <div className="flex items-center justify-center py-4">
              <RefreshCw className="h-4 w-4 animate-spin text-sky-500" />
              <span className="ml-2 text-xs text-gray-400">Загрузка...</span>
            </div>
          ) : cameraPorts && cameraPorts.length > 0 ? (
            <div className="space-y-0.5 max-h-96 overflow-y-auto">
              {cameraPorts.map((cam) => (
                <CameraPortRow key={cam.port} cam={cam} switchId={switchId} isSuperuser={isSuperuser} />
              ))}
            </div>
          ) : (
            <div className="text-xs text-gray-400 text-center py-3">Нет портов на камерных VLAN</div>
          )}
        </div>
      )}
    </div>
  );
}
