import { useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Pencil, Trash2, Copy, RefreshCw, CircleCheck, CircleX } from "lucide-react";
import { useAuth } from "../auth";
import {
  createComputer,
  deleteComputer,
  getComputers,
  pollAllComputers,
  pollComputer,
  updateComputer,
  type Computer,
} from "../client";
import { useEntityAutoPoll } from "../hooks/useEntityAutoPoll";
import { useDebouncedValue } from "../hooks/useDebouncedValue";

type StatusFilter = "all" | "online" | "offline";
type ComputerForm = {
  hostname: string;
  location: string;
  comment: string;
};

const emptyForm: ComputerForm = {
  hostname: "",
  location: "",
  comment: "",
};

export default function ComputersPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isSuperuser = Boolean(user?.is_superuser);
  const [q, setQ] = useState("");
  const debouncedQ = useDebouncedValue(q, 300);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editing, setEditing] = useState<Computer | null>(null);
  const [form, setForm] = useState<ComputerForm>(emptyForm);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [pollingIds, setPollingIds] = useState<Set<string>>(new Set());

  const { data, isLoading } = useQuery({
    queryKey: ["computers", debouncedQ],
    queryFn: () => getComputers(debouncedQ || undefined),
    placeholderData: keepPreviousData,
  });

  const rows = useMemo(() => data?.data ?? [], [data]);
  const sortedRows = useMemo(() => {
    const rank = (value: boolean | null) => (value === true ? 0 : value === null ? 1 : 2);
    return [...rows].sort((a, b) => rank(a.is_online) - rank(b.is_online));
  }, [rows]);
  const visibleRows = useMemo(() => {
    if (statusFilter === "online") return sortedRows.filter((row) => row.is_online === true);
    if (statusFilter === "offline") return sortedRows.filter((row) => row.is_online === false);
    return sortedRows;
  }, [sortedRows, statusFilter]);
  const onlineCount = rows.filter((row) => row.is_online === true).length;
  const offlineCount = rows.filter((row) => row.is_online === false).length;

  const refetchAll = () => queryClient.invalidateQueries({ queryKey: ["computers"] });

  const createMut = useMutation({
    mutationFn: createComputer,
    onSuccess: () => {
      setIsModalOpen(false);
      setEditing(null);
      setForm(emptyForm);
      refetchAll();
    },
  });
  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<Computer> }) => updateComputer(id, payload),
    onSuccess: () => {
      setIsModalOpen(false);
      setEditing(null);
      setForm(emptyForm);
      refetchAll();
    },
  });
  const deleteMut = useMutation({
    mutationFn: deleteComputer,
    onSuccess: refetchAll,
  });
  const pollMut = useMutation({
    mutationFn: pollComputer,
    onMutate: (id) => setPollingIds((state) => new Set(state).add(id)),
    onSettled: (_data, _error, id) => {
      setPollingIds((state) => {
        const next = new Set(state);
        next.delete(id);
        return next;
      });
      refetchAll();
    },
  });
  const pollAllMut = useMutation({
    mutationFn: pollAllComputers,
    onSuccess: refetchAll,
  });

  useEntityAutoPoll({
    enabled: !isModalOpen,
    queryKeyRoot: "computers",
    poll: pollAllComputers,
  });
  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setIsModalOpen(true);
  };

  const openEdit = (row: Computer) => {
    setEditing(row);
    setForm({
      hostname: row.hostname,
      location: row.location ?? "",
      comment: row.comment ?? "",
    });
    setIsModalOpen(true);
  };

  const submit = () => {
    if (!form.hostname.trim()) return;
    if (editing) {
      updateMut.mutate({ id: editing.id, payload: form });
      return;
    }
    createMut.mutate(form);
  };

  const copyHostname = async (hostname: string) => {
    if (!hostname || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(hostname);
    } catch {
      // ignore clipboard errors
    }
  };

  return (
    <div className="space-y-6">
      <div className="app-panel p-3">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="relative w-full md:max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Умный поиск: hostname, локация, комментарий (A/А)"
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
              Опросить все
            </button>
            {isSuperuser && (
              <button onClick={openCreate} className="app-btn-secondary inline-flex items-center gap-2 px-4 py-2 text-sm">
                <Plus className="h-4 w-4" />
                Добавить компьютер
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Stat label="Всего" value={rows.length} active={statusFilter === "all"} onClick={() => setStatusFilter("all")} />
        <Stat
          label="Онлайн"
          value={onlineCount}
          active={statusFilter === "online"}
          onClick={() => setStatusFilter("online")}
        />
        <Stat
          label="Оффлайн"
          value={offlineCount}
          active={statusFilter === "offline"}
          onClick={() => setStatusFilter("offline")}
        />
      </div>

      <div className="space-y-3">
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="app-panel p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-3 flex-1">
                    <div className="app-skeleton h-5 w-48" />
                    <div className="grid gap-2 sm:grid-cols-3">
                      <div className="app-skeleton h-4" />
                      <div className="app-skeleton h-4" />
                      <div className="app-skeleton h-4" />
                    </div>
                  </div>
                  <div className="app-skeleton h-9 w-44" />
                </div>
              </div>
            ))}
          </div>
        ) : visibleRows.length === 0 ? (
          <div className="app-empty p-8 text-center text-gray-500">Компьютеры не найдены</div>
        ) : (
          visibleRows.map((row) => {
            const polledAt = row.last_polled_at ? new Date(row.last_polled_at).toLocaleString("ru-RU") : null;
            return (
            <div key={row.id} className="app-panel p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <div className="text-base font-semibold text-slate-900">{row.hostname}</div>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                        row.is_online === true
                          ? "bg-emerald-100 text-emerald-700"
                          : row.is_online === false
                            ? "bg-rose-100 text-rose-700"
                            : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {row.is_online === true ? (
                        <CircleCheck className="h-3.5 w-3.5" />
                      ) : row.is_online === false ? (
                        <CircleX className="h-3.5 w-3.5" />
                      ) : (
                        <div className="h-3.5 w-3.5 rounded-full border border-slate-400" />
                      )}
                      {row.is_online === true ? "online" : row.is_online === false ? "offline" : "не опрошен"}
                    </span>
                  </div>
                  <div className="grid gap-1 text-xs text-gray-500 sm:grid-cols-2">
                    <div>Локация/магазин: {row.location || "—"}</div>
                    <div>Создано: {new Date(row.created_at).toLocaleString("ru-RU")}</div>
                    <div>Проверка: {polledAt || "ещё не было"}</div>
                  </div>
                  {row.is_online === false && (
                    <div className="text-xs text-rose-600">
                      Причина оффлайна: {row.reachability_reason === "dns_unresolved" ? "hostname не резолвится" : "порты недоступны"}
                    </div>
                  )}
                  {row.comment && <div className="text-sm text-slate-600">Комментарий: {row.comment}</div>}
                </div>
                <div className="flex gap-2 flex-wrap">
                  <button
                    onClick={() => copyHostname(row.hostname)}
                    className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm"
                    title="Скопировать hostname"
                  >
                    <Copy className="h-4 w-4" />
                    Копировать hostname
                  </button>
                  <button
                    onClick={() => pollMut.mutate(row.id)}
                    disabled={pollingIds.has(row.id)}
                    className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm"
                    title="Проверить доступность по сети"
                  >
                    <RefreshCw className={`h-4 w-4 ${pollingIds.has(row.id) ? "animate-spin" : ""}`} />
                    Опросить
                  </button>
                  {isSuperuser && (
                    <>
                      <button onClick={() => openEdit(row)} className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm">
                        <Pencil className="h-4 w-4" />
                        Редактировать
                      </button>
                      <button
                        onClick={() => deleteMut.mutate(row.id)}
                        className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm"
                      >
                        <Trash2 className="h-4 w-4" />
                        Удалить
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>
            );
          })
        )}
      </div>

      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
          <div className="app-panel w-full max-w-2xl p-5 space-y-4 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-slate-900">{editing ? "Редактировать компьютер" : "Новый компьютер"}</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Input
                label="Hostname*"
                value={form.hostname}
                onChange={(v) => setForm((s) => ({ ...s, hostname: v }))}
              />
              <Input
                label="Локация / магазин"
                value={form.location}
                onChange={(v) => setForm((s) => ({ ...s, location: v }))}
              />
            </div>
            <label className="text-sm block">
              <span className="mb-1 block text-slate-600">Комментарий</span>
              <textarea
                className="app-input w-full p-3 text-sm min-h-20"
                value={form.comment}
                onChange={(e) => setForm((s) => ({ ...s, comment: e.target.value }))}
              />
            </label>
            <div className="flex justify-end gap-2">
              <button onClick={() => setIsModalOpen(false)} className="app-btn-secondary px-4 py-2 text-sm">
                Отмена
              </button>
              <button onClick={submit} className="app-btn-primary px-4 py-2 text-sm">
                Сохранить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  active,
  onClick,
}: {
  label: string;
  value: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`app-stat text-left px-4 py-3 transition ${active ? "ring-2 ring-rose-400/50" : "hover:shadow-sm"}`}
      type="button"
    >
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </button>
  );
}

function Input({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="text-sm">
      <span className="mb-1 block text-slate-600">{label}</span>
      <input className="app-input w-full py-2 px-3 text-sm" value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}
