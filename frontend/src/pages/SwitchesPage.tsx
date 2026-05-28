import { useState } from "react";
import { keepPreviousData, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Search, Network } from "lucide-react";
import { useAuth } from "../auth";
import type { NetworkSwitch } from "../client";
import { getSwitches, createSwitch, updateSwitch, deleteSwitch, pollSwitch, pollAllSwitches } from "../client";
import SwitchForm from "../components/SwitchForm";
import SwitchCard from "../components/SwitchCard";
import SwitchPortsTable from "../components/SwitchPortsTable";
import { useEntityAutoPoll } from "../hooks/useEntityAutoPoll";
import { useDebouncedValue } from "../hooks/useDebouncedValue";

type StatusFilter = "all" | "online" | "offline";

export default function SwitchesPage() {
  const { user } = useAuth();
  const isSuperuser = user?.is_superuser ?? false;
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState<NetworkSwitch | null>(null);
  const [pollingId, setPollingId] = useState<string | null>(null);
  const [portsTarget, setPortsTarget] = useState<NetworkSwitch | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const { data, isLoading } = useQuery({
    queryKey: ["switches", debouncedSearch],
    queryFn: () => getSwitches(debouncedSearch || undefined),
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  });

  const switches = data?.data ?? [];
  const onlineCount = switches.filter((s) => s.is_online === true).length;
  const sortedSwitches = [...switches].sort((a, b) => {
    const rank = (value: boolean | null) => (value === true ? 0 : value === null ? 1 : 2);
    return rank(a.is_online) - rank(b.is_online);
  });
  const offlineCount = switches.filter((s) => s.is_online === false).length;
  const visibleSwitches = sortedSwitches.filter((sw) => {
    if (statusFilter === "online") return sw.is_online === true;
    if (statusFilter === "offline") return sw.is_online === false;
    return true;
  });

  const pollMut = useMutation({
    mutationFn: (id: string) => pollSwitch(id),
    onMutate: (id) => setPollingId(id),
    onSettled: () => {
      setPollingId(null);
      queryClient.invalidateQueries({ queryKey: ["switches"] });
    },
  });
  const pollAllMut = useMutation({
    mutationFn: pollAllSwitches,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["switches"] }),
  });

  useEntityAutoPoll({
    enabled: !showForm && !portsTarget,
    queryKeyRoot: "switches",
    poll: pollAllSwitches,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteSwitch(id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["switches"] }),
  });

  const handleSave = async (formData: Record<string, unknown>) => {
    if (editTarget) {
      await updateSwitch(editTarget.id, formData);
    } else {
      await createSwitch(formData as Parameters<typeof createSwitch>[0]);
    }
    setShowForm(false);
    setEditTarget(null);
    queryClient.invalidateQueries({ queryKey: ["switches"] });
  };

  const handleDelete = (id: string) => {
    if (confirm("Удалить свитч?")) deleteMut.mutate(id);
  };

  return (
    <div className="space-y-6">
      <div className="app-panel p-3">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="relative w-full md:max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
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
                onClick={() => { setEditTarget(null); setShowForm(true); }}
                className="app-btn-secondary inline-flex items-center gap-2 px-4 py-2 text-sm transition"
              >
                <Plus className="h-4 w-4" />
                Добавить свитч
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid gap-4 grid-cols-1 sm:grid-cols-3">
        <Stat label="Всего" value={switches.length} color="text-gray-900" bg="bg-gray-100" isActive={statusFilter === "all"} onClick={() => setStatusFilter("all")} />
        <Stat label="Онлайн" value={onlineCount} color="text-emerald-700" bg="bg-emerald-50" isActive={statusFilter === "online"} onClick={() => setStatusFilter("online")} />
        <Stat label="Оффлайн" value={offlineCount} color="text-red-700" bg="bg-red-50" isActive={statusFilter === "offline"} onClick={() => setStatusFilter("offline")} />
      </div>

      {/* Grid */}
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="app-panel p-5 space-y-4">
              <div className="flex items-center gap-3">
                <div className="app-skeleton h-10 w-10" />
                <div className="space-y-2 flex-1">
                  <div className="app-skeleton h-4 w-2/3" />
                  <div className="app-skeleton h-3 w-1/2" />
                </div>
              </div>
              <div className="app-skeleton h-24 w-full" />
            </div>
          ))}
        </div>
      ) : visibleSwitches.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {visibleSwitches.map((sw) => (
            <SwitchCard
              key={sw.id}
              sw={sw}
              onPoll={(id) => pollMut.mutate(id)}
              onEdit={(s) => { setEditTarget(s); setShowForm(true); }}
              onDelete={handleDelete}
              onOpenPorts={(s) => setPortsTarget(s)}
              isPolling={pollingId === sw.id}
              isSuperuser={isSuperuser}
            />
          ))}
        </div>
      ) : (
        <div className="app-empty text-center py-16 text-gray-400">
          <Network className="h-12 w-12 mx-auto mb-3 text-gray-300" />
          <p>Нет добавленных свитчей</p>
          {isSuperuser && (
            <button
              onClick={() => { setEditTarget(null); setShowForm(true); }}
              className="mt-3 text-rose-600 hover:text-rose-700 text-sm font-medium"
            >
              Добавить первый свитч
            </button>
          )}
        </div>
      )}

      {/* Form modal */}
      {showForm && (
        <SwitchForm
          initial={editTarget ?? undefined}
          onSave={handleSave}
          onCancel={() => { setShowForm(false); setEditTarget(null); }}
        />
      )}
      {portsTarget && (
        <SwitchPortsTable
          sw={portsTarget}
          isSuperuser={isSuperuser}
          onClose={() => setPortsTarget(null)}
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
