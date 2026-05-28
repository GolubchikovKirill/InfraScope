import { useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Search, Trash2, Pencil, CircleCheck, CircleX, Download, Copy } from "lucide-react";
import { useAuth } from "../auth";
import {
  createCashRegister,
  deleteCashRegister,
  getCashRegisters,
  getCashRegistersExportUrl,
  pollAllCashRegisters,
  pollCashRegister,
  updateCashRegister,
  type CashRegister,
} from "../client";
import { useEntityAutoPoll } from "../hooks/useEntityAutoPoll";
import { useDebouncedValue } from "../hooks/useDebouncedValue";

type StatusFilter = "all" | "online" | "offline";
type CashForm = {
  kkm_number: string;
  store_number: string;
  store_code: string;
  serial_number: string;
  inventory_number: string;
  terminal_id_rs: string;
  terminal_id_sber: string;
  windows_version: string;
  kkm_type: "retail" | "shtrih";
  cash_number: string;
  hostname: string;
  comment: string;
};

const emptyForm: CashForm = {
  kkm_number: "",
  store_number: "",
  store_code: "",
  serial_number: "",
  inventory_number: "",
  terminal_id_rs: "",
  terminal_id_sber: "",
  windows_version: "",
  kkm_type: "retail",
  cash_number: "",
  hostname: "",
  comment: "",
};

export default function CashRegistersPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isSuperuser = Boolean(user?.is_superuser);
  const [q, setQ] = useState("");
  const debouncedQ = useDebouncedValue(q, 300);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editing, setEditing] = useState<CashRegister | null>(null);
  const [form, setForm] = useState<CashForm>(emptyForm);
  const [pollingIds, setPollingIds] = useState<Set<string>>(new Set());

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["cash-registers", debouncedQ],
    queryFn: () => getCashRegisters(debouncedQ || undefined),
    placeholderData: keepPreviousData,
  });

  const rows = data?.data ?? [];
  const sortedRows = useMemo(
    () => [...rows].sort((a, b) => Number(Boolean(b.is_online)) - Number(Boolean(a.is_online))),
    [rows],
  );
  const visibleRows = useMemo(() => {
    if (statusFilter === "online") return sortedRows.filter((r) => r.is_online);
    if (statusFilter === "offline") return sortedRows.filter((r) => r.is_online === false);
    return sortedRows;
  }, [sortedRows, statusFilter]);
  const onlineCount = rows.filter((r) => r.is_online).length;
  const offlineCount = rows.filter((r) => r.is_online === false).length;

  const refetchAll = () => {
    queryClient.invalidateQueries({ queryKey: ["cash-registers"] });
  };

  const createMut = useMutation({
    mutationFn: createCashRegister,
    onSuccess: () => {
      setIsModalOpen(false);
      setForm(emptyForm);
      refetchAll();
    },
  });
  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<CashRegister> }) => updateCashRegister(id, payload),
    onSuccess: () => {
      setIsModalOpen(false);
      setEditing(null);
      setForm(emptyForm);
      refetchAll();
    },
  });
  const deleteMut = useMutation({
    mutationFn: deleteCashRegister,
    onSuccess: refetchAll,
  });
  const pollMut = useMutation({
    mutationFn: pollCashRegister,
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
    mutationFn: pollAllCashRegisters,
    onSuccess: refetchAll,
  });

  useEntityAutoPoll({
    enabled: !isModalOpen,
    queryKeyRoot: "cash-registers",
    poll: pollAllCashRegisters,
  });
  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setIsModalOpen(true);
  };

  const openEdit = (item: CashRegister) => {
    setEditing(item);
    setForm({
      kkm_number: item.kkm_number ?? "",
      store_number: item.store_number ?? "",
      store_code: item.store_code ?? "",
      serial_number: item.serial_number ?? "",
      inventory_number: item.inventory_number ?? "",
      terminal_id_rs: item.terminal_id_rs ?? "",
      terminal_id_sber: item.terminal_id_sber ?? "",
      windows_version: item.windows_version ?? "",
      kkm_type: item.kkm_type,
      cash_number: item.cash_number ?? "",
      hostname: item.hostname ?? "",
      comment: item.comment ?? "",
    });
    setIsModalOpen(true);
  };

  const submit = () => {
    if (!form.kkm_number.trim() || !form.hostname.trim()) return;
    if (editing) {
      updateMut.mutate({ id: editing.id, payload: form });
      return;
    }
    createMut.mutate(form);
  };

  const copyHostname = async (item: Pick<CashRegister, "hostname">) => {
    const target = (item.hostname || "").trim();
    if (!target || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(target);
    } catch {
      // Ignore clipboard errors in unsupported environments.
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
              placeholder="Умный поиск: ККМ, магазин, hostname, код, серийный (A/А)"
              className="app-input w-full pl-10 pr-4 py-2 text-sm"
            />
          </div>
          <div className="app-toolbar-actions flex flex-wrap gap-2">
            <a
              href={getCashRegistersExportUrl(debouncedQ || undefined)}
              className="app-btn-secondary inline-flex items-center gap-2 px-4 py-2 text-sm"
            >
              <Download className="h-4 w-4" />
              Экспорт CSV
            </a>
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
                Добавить кассу
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
                    <div className="app-skeleton h-5 w-56" />
                    <div className="grid gap-2 sm:grid-cols-3">
                      <div className="app-skeleton h-4" />
                      <div className="app-skeleton h-4" />
                      <div className="app-skeleton h-4" />
                    </div>
                    <div className="grid gap-2 sm:grid-cols-4">
                      <div className="app-skeleton h-4" />
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
          <div className="app-empty p-8 text-center text-gray-500">Кассы не найдены</div>
        ) : (
          visibleRows.map((item) => (
            <div key={item.id} className="app-panel p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <div className="text-base font-semibold text-slate-900">ККМ №{item.kkm_number}</div>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                        item.is_online === true
                          ? "bg-emerald-100 text-emerald-700"
                          : item.is_online === false
                            ? "bg-rose-100 text-rose-700"
                            : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {item.is_online === true ? (
                        <CircleCheck className="h-3.5 w-3.5" />
                      ) : item.is_online === false ? (
                        <CircleX className="h-3.5 w-3.5" />
                      ) : (
                        <div className="h-3.5 w-3.5 rounded-full border border-slate-400" />
                      )}
                      {item.is_online === true ? "online" : item.is_online === false ? "offline" : "не опрошена"}
                    </span>
                  </div>
                  <div className="text-sm text-slate-600">
                    Hostname: <span className="font-medium">{item.hostname}</span> · Тип ККМ:{" "}
                    <span className="font-medium">{item.kkm_type === "retail" ? "РИТЕЙЛ" : "ШТРИХ"}</span>
                    {item.hostname && (
                      <button
                        onClick={() => copyHostname(item)}
                        className="ml-1 inline-flex items-center rounded p-0.5 text-gray-400 hover:text-rose-600 hover:bg-gray-100 transition"
                        title="Скопировать hostname"
                      >
                        <Copy className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                  {item.is_online === false && (
                    <div className="text-xs text-rose-600">
                      Причина оффлайна:{" "}
                      {item.reachability_reason === "dns_unresolved"
                        ? "hostname не резолвится"
                        : item.reachability_reason === "port_closed"
                          ? "сетевые порты недоступны"
                          : "хост недоступен"}
                    </div>
                  )}
                  <div className="grid gap-1 text-xs text-gray-500 sm:grid-cols-2 lg:grid-cols-3">
                    <div>
                      Проверка:{" "}
                      {item.last_polled_at ? new Date(item.last_polled_at).toLocaleString("ru-RU") : "ещё не было"}
                    </div>
                    <div>Номер магазина: {item.store_number || "—"}</div>
                    <div>Код ТТ: {item.store_code || "—"}</div>
                    <div>Серийный: {item.serial_number || "—"}</div>
                    <div>Инв. №: {item.inventory_number || "—"}</div>
                    <div>ID РС: {item.terminal_id_rs || "—"}</div>
                    <div>ID Сбер: {item.terminal_id_sber || "—"}</div>
                    <div>Версия Windows: {item.windows_version || "—"}</div>
                    <div>Номер кассы: {item.cash_number || "—"}</div>
                    <div>Hostname для NetSupport: {item.hostname || "—"}</div>
                  </div>
                  {item.comment && <div className="text-sm text-slate-600">Комментарий: {item.comment}</div>}
                </div>
                <div className="flex gap-2 flex-wrap">
                  <button
                    onClick={() => copyHostname(item)}
                    disabled={!item.hostname}
                    className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm disabled:opacity-40"
                    title={item.hostname ? "Скопировать hostname для ручного подключения" : "Hostname не заполнен"}
                  >
                    <Copy className="h-4 w-4" />
                    Копировать hostname
                  </button>
                  <button
                    onClick={() => pollMut.mutate(item.id)}
                    disabled={pollingIds.has(item.id)}
                    className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm"
                  >
                    <RefreshCw className={`h-4 w-4 ${pollingIds.has(item.id) ? "animate-spin" : ""}`} />
                    Обновить
                  </button>
                  {isSuperuser && (
                    <>
                      <button onClick={() => openEdit(item)} className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm">
                        <Pencil className="h-4 w-4" />
                        Редактировать
                      </button>
                      <button
                        onClick={() => deleteMut.mutate(item.id)}
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
          ))
        )}
      </div>

      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
          <div className="app-panel w-full max-w-3xl p-5 space-y-4 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-slate-900">{editing ? "Редактировать кассу" : "Новая касса"}</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Input label="№ ККМ*" value={form.kkm_number} onChange={(v) => setForm((s) => ({ ...s, kkm_number: v }))} />
              <Input
                label="Hostname в сети*"
                value={form.hostname}
                onChange={(v) => setForm((s) => ({ ...s, hostname: v }))}
              />
              <Input
                label="Номер магазина"
                value={form.store_number}
                onChange={(v) => setForm((s) => ({ ...s, store_number: v }))}
              />
              <Input
                label="Код торговой точки"
                value={form.store_code}
                onChange={(v) => setForm((s) => ({ ...s, store_code: v }))}
              />
              <Input
                label="Серийный номер"
                value={form.serial_number}
                onChange={(v) => setForm((s) => ({ ...s, serial_number: v }))}
              />
              <Input
                label="Инвентаризационный №"
                value={form.inventory_number}
                onChange={(v) => setForm((s) => ({ ...s, inventory_number: v }))}
              />
              <Input
                label="ID терминала Русский Стандарт"
                value={form.terminal_id_rs}
                onChange={(v) => setForm((s) => ({ ...s, terminal_id_rs: v }))}
              />
              <Input
                label="ID терминала Сбер"
                value={form.terminal_id_sber}
                onChange={(v) => setForm((s) => ({ ...s, terminal_id_sber: v }))}
              />
              <Input
                label="Версия Windows"
                value={form.windows_version}
                onChange={(v) => setForm((s) => ({ ...s, windows_version: v }))}
              />
              <Input
                label="Номер кассы"
                value={form.cash_number}
                onChange={(v) => setForm((s) => ({ ...s, cash_number: v }))}
              />
              <label className="text-sm">
                <span className="mb-1 block text-slate-600">Тип ККМ</span>
                <select
                  className="app-input w-full py-2 px-3 text-sm"
                  value={form.kkm_type}
                  onChange={(e) => setForm((s) => ({ ...s, kkm_type: e.target.value as "retail" | "shtrih" }))}
                >
                  <option value="retail">РИТЕЙЛ</option>
                  <option value="shtrih">ШТРИХ</option>
                </select>
              </label>
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

      {(isFetching || createMut.isPending || updateMut.isPending) && (
        <div className="fixed bottom-4 right-4 app-panel px-4 py-2 text-sm text-slate-600">Сохранение / обновление...</div>
      )}
    </div>
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
