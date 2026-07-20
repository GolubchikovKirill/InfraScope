import { useMemo, useState, type ReactNode } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CircleCheck,
  CircleHelp,
  CircleX,
  Copy,
  Download,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Store,
  Trash2,
} from "lucide-react";
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

type StatusFilter = "all" | "online" | "offline" | "unknown" | "attention";
type ZoneFilter = "all" | "DF" | "DP";
type CashForm = {
  location_zone: "" | "DF" | "DP";
  kkm_number: string;
  store_number: string;
  store_code: string;
  sber_store_code: string;
  serial_number: string;
  inventory_number: string;
  terminal_id_rs: string;
  terminal_id_sber: string;
  windows_version: string;
  kkm_type: "retail" | "shtrih";
  rosenzweig_number: string;
  cash_number: string;
  hostname: string;
  netsupport_target: string;
  second_screen: string;
  piot_status: string;
  cash_drawer: string;
  terminal_status: string;
  comment: string;
};

const emptyForm: CashForm = {
  location_zone: "",
  kkm_number: "",
  store_number: "",
  store_code: "",
  sber_store_code: "",
  serial_number: "",
  inventory_number: "",
  terminal_id_rs: "",
  terminal_id_sber: "",
  windows_version: "",
  kkm_type: "retail",
  rosenzweig_number: "",
  cash_number: "",
  hostname: "",
  netsupport_target: "",
  second_screen: "",
  piot_status: "",
  cash_drawer: "",
  terminal_status: "",
  comment: "",
};

function isAttention(item: CashRegister) {
  const piot = (item.piot_status || "").trim().toLocaleUpperCase("ru-RU");
  const drawer = (item.cash_drawer || "").trim().toLocaleLowerCase("ru-RU");
  const piotProblem = Boolean(piot) && (piot.includes("НЕ ОБНОВЛЕН") || !piot.includes("ОБНОВЛЕН"));
  const drawerProblem = Boolean(drawer) && drawer !== "да";
  return Boolean(item.terminal_status || piotProblem || drawerProblem);
}

function compareText(a: string | null, b: string | null) {
  return (a || "").localeCompare(b || "", "ru", { numeric: true, sensitivity: "base" });
}

export default function CashRegistersPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isSuperuser = Boolean(user?.is_superuser);
  const [q, setQ] = useState("");
  const debouncedQ = useDebouncedValue(q, 300);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [zoneFilter, setZoneFilter] = useState<ZoneFilter>("all");
  const [storeFilter, setStoreFilter] = useState("all");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editing, setEditing] = useState<CashRegister | null>(null);
  const [form, setForm] = useState<CashForm>(emptyForm);
  const [pollingIds, setPollingIds] = useState<Set<string>>(new Set());

  const { data, isLoading, isFetching, isError } = useQuery({
    queryKey: ["cash-registers", debouncedQ],
    queryFn: () => getCashRegisters(debouncedQ || undefined),
    placeholderData: keepPreviousData,
  });

  const rows = data?.data ?? [];
  const storeOptions = useMemo(
    () => [...new Set(rows.map((item) => item.store_number).filter((item): item is string => Boolean(item)))].sort(compareText),
    [rows],
  );
  const visibleRows = useMemo(() => {
    return rows
      .filter((item) => zoneFilter === "all" || item.location_zone === zoneFilter)
      .filter((item) => storeFilter === "all" || item.store_number === storeFilter)
      .filter((item) => {
        if (statusFilter === "online") return item.is_online === true;
        if (statusFilter === "offline") return item.is_online === false;
        if (statusFilter === "unknown") return item.is_online === null;
        if (statusFilter === "attention") return isAttention(item);
        return true;
      })
      .sort((a, b) => {
        const zone = compareText(a.location_zone, b.location_zone);
        if (zone) return zone;
        const store = compareText(a.store_number, b.store_number);
        if (store) return store;
        return (a.source_order ?? Number.MAX_SAFE_INTEGER) - (b.source_order ?? Number.MAX_SAFE_INTEGER) || compareText(a.kkm_number, b.kkm_number);
      });
  }, [rows, statusFilter, storeFilter, zoneFilter]);
  const groups = useMemo(() => {
    const result: Array<{ key: string; zone: string; store: string; rows: CashRegister[] }> = [];
    for (const item of visibleRows) {
      const zone = item.location_zone || "Без зоны";
      const store = item.store_number || "Без магазина";
      const key = `${zone}:${store}`;
      const current = result[result.length - 1];
      if (!current || current.key !== key) result.push({ key, zone, store, rows: [item] });
      else current.rows.push(item);
    }
    return result;
  }, [visibleRows]);

  const onlineCount = rows.filter((item) => item.is_online === true).length;
  const offlineCount = rows.filter((item) => item.is_online === false).length;
  const attentionCount = rows.filter(isAttention).length;
  const dfCount = rows.filter((item) => item.location_zone === "DF").length;
  const dpCount = rows.filter((item) => item.location_zone === "DP").length;

  const refetchAll = () => queryClient.invalidateQueries({ queryKey: ["cash-registers"] });
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
  const deleteMut = useMutation({ mutationFn: deleteCashRegister, onSuccess: refetchAll });
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
  const pollAllMut = useMutation({ mutationFn: pollAllCashRegisters, onSuccess: refetchAll });

  // Real device polling now runs on a schedule in the backend (Celery Beat),
  // so this no longer triggers a real poll from every open tab - it just
  // refreshes from cache. Realtime updates arrive via WebSocket regardless.
  useEntityAutoPoll({
    enabled: !isModalOpen,
    queryKeyRoot: "cash-registers",
    poll: () => Promise.resolve(),
  });
  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setIsModalOpen(true);
  };
  const openEdit = (item: CashRegister) => {
    setEditing(item);
    setForm({
      location_zone: item.location_zone ?? "",
      kkm_number: item.kkm_number ?? "",
      store_number: item.store_number ?? "",
      store_code: item.store_code ?? "",
      sber_store_code: item.sber_store_code ?? "",
      serial_number: item.serial_number ?? "",
      inventory_number: item.inventory_number ?? "",
      terminal_id_rs: item.terminal_id_rs ?? "",
      terminal_id_sber: item.terminal_id_sber ?? "",
      windows_version: item.windows_version ?? "",
      kkm_type: item.kkm_type,
      rosenzweig_number: item.rosenzweig_number ?? "",
      cash_number: item.cash_number ?? "",
      hostname: item.hostname ?? "",
      netsupport_target: item.netsupport_target ?? "",
      second_screen: item.second_screen ?? "",
      piot_status: item.piot_status ?? "",
      cash_drawer: item.cash_drawer ?? "",
      terminal_status: item.terminal_status ?? "",
      comment: item.comment ?? "",
    });
    setIsModalOpen(true);
  };
  const submit = () => {
    if (!form.kkm_number.trim() || !form.hostname.trim()) return;
    const payload = { ...form, location_zone: form.location_zone || undefined };
    if (editing) updateMut.mutate({ id: editing.id, payload });
    else createMut.mutate(payload);
  };
  const copyText = async (value: string | null) => {
    const target = (value || "").trim();
    if (!target || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(target);
    } catch {
      // Clipboard is optional in older browsers.
    }
  };

  return (
    <div className="space-y-5">
      <div className="app-panel p-4 space-y-3">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="relative w-full xl:max-w-xl">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="ККМ, магазин, hostname, терминал, код точки, комментарий"
              className="app-input w-full py-2 pl-10 pr-4 text-sm"
            />
          </div>
          <div className="app-toolbar-actions flex flex-wrap gap-2">
            <a href={getCashRegistersExportUrl(debouncedQ || undefined)} className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm">
              <Download className="h-4 w-4" /> Экспорт CSV
            </a>
            <button onClick={() => pollAllMut.mutate()} disabled={pollAllMut.isPending} className="app-btn-primary inline-flex items-center gap-2 px-3 py-2 text-sm disabled:opacity-50">
              <RefreshCw className={`h-4 w-4 ${pollAllMut.isPending ? "animate-spin" : ""}`} /> Опросить все
            </button>
            {isSuperuser && (
              <button onClick={openCreate} className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm">
                <Plus className="h-4 w-4" /> Добавить кассу
              </button>
            )}
          </div>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <FilterSelect label="Зона" value={zoneFilter} onChange={(value) => setZoneFilter(value as ZoneFilter)}>
            <option value="all">Все зоны</option><option value="DF">Duty Free</option><option value="DP">Duty Paid</option>
          </FilterSelect>
          <FilterSelect label="Магазин" value={storeFilter} onChange={setStoreFilter}>
            <option value="all">Все магазины</option>
            {storeOptions.map((store) => <option key={store} value={store}>{store}</option>)}
          </FilterSelect>
          <FilterSelect label="Состояние" value={statusFilter} onChange={(value) => setStatusFilter(value as StatusFilter)}>
            <option value="all">Все состояния</option><option value="online">Онлайн</option><option value="offline">Оффлайн</option><option value="unknown">Не опрошены</option><option value="attention">Требуют внимания</option>
          </FilterSelect>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Всего" value={data?.count ?? rows.length} active={statusFilter === "all" && zoneFilter === "all"} onClick={() => { setStatusFilter("all"); setZoneFilter("all"); }} />
        <Stat label="Duty Free" value={dfCount} active={zoneFilter === "DF"} onClick={() => setZoneFilter("DF")} tone="sky" />
        <Stat label="Duty Paid" value={dpCount} active={zoneFilter === "DP"} onClick={() => setZoneFilter("DP")} tone="violet" />
        <Stat label="Онлайн" value={onlineCount} active={statusFilter === "online"} onClick={() => setStatusFilter("online")} tone="green" />
        <Stat label="Оффлайн" value={offlineCount} active={statusFilter === "offline"} onClick={() => setStatusFilter("offline")} tone="red" />
        <Stat label="Требуют внимания" value={attentionCount} active={statusFilter === "attention"} onClick={() => setStatusFilter("attention")} tone="amber" />
      </div>

      {isError ? (
        <div className="app-panel p-8 text-center text-rose-600">Не удалось загрузить список касс.</div>
      ) : isLoading ? (
        <div className="space-y-3">{Array.from({ length: 4 }).map((_, index) => <div key={index} className="app-panel h-32 app-skeleton" />)}</div>
      ) : groups.length === 0 ? (
        <div className="app-empty p-10 text-center text-gray-500">По выбранным фильтрам кассы не найдены</div>
      ) : (
        <div className="space-y-4">
          {groups.map((group) => (
            <section key={group.key} className="app-panel overflow-hidden">
              <div className="flex flex-col gap-2 border-b border-slate-200 bg-slate-50/70 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3">
                  <div className={`rounded-lg p-2 ${group.zone === "DF" ? "bg-sky-100 text-sky-700" : "bg-violet-100 text-violet-700"}`}><Store className="h-4 w-4" /></div>
                  <div><h2 className="font-semibold text-slate-900">{group.store}</h2><p className="text-xs text-slate-500">{group.zone === "DF" ? "Duty Free" : group.zone === "DP" ? "Duty Paid" : group.zone}</p></div>
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <Badge>{group.rows.length} касс</Badge>
                  <Badge tone="green">{group.rows.filter((item) => item.is_online === true).length} онлайн</Badge>
                  {group.rows.some(isAttention) && <Badge tone="amber">{group.rows.filter(isAttention).length} требуют внимания</Badge>}
                </div>
              </div>
              <div className="divide-y divide-slate-200">
                {group.rows.map((item) => (
                  <CashRow
                    key={item.id}
                    item={item}
                    isSuperuser={isSuperuser}
                    isPolling={pollingIds.has(item.id)}
                    onCopy={copyText}
                    onPoll={() => pollMut.mutate(item.id)}
                    onEdit={() => openEdit(item)}
                    onDelete={() => {
                      if (window.confirm(`Удалить кассу ${item.kkm_number}?`)) deleteMut.mutate(item.id);
                    }}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
          <div className="app-panel max-h-[92vh] w-full max-w-4xl space-y-4 overflow-y-auto p-5">
            <h2 className="text-lg font-semibold text-slate-900">{editing ? "Редактировать кассу" : "Новая касса"}</h2>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
              <label className="text-sm"><span className="mb-1 block text-slate-600">Зона</span><select className="app-input w-full px-3 py-2 text-sm" value={form.location_zone} onChange={(event) => setForm((state) => ({ ...state, location_zone: event.target.value as CashForm["location_zone"] }))}><option value="">Не указана</option><option value="DF">Duty Free</option><option value="DP">Duty Paid</option></select></label>
              <Input label="№ ККМ*" value={form.kkm_number} onChange={(value) => setForm((state) => ({ ...state, kkm_number: value }))} />
              <Input label="Hostname в сети*" value={form.hostname} onChange={(value) => setForm((state) => ({ ...state, hostname: value }))} />
              <Input label="Магазин" value={form.store_number} onChange={(value) => setForm((state) => ({ ...state, store_number: value }))} />
              <Input label="Код ТТ Русский Стандарт" value={form.store_code} onChange={(value) => setForm((state) => ({ ...state, store_code: value }))} />
              <Input label="Код ТТ Сбер" value={form.sber_store_code} onChange={(value) => setForm((state) => ({ ...state, sber_store_code: value }))} />
              <Input label="Серийный номер" value={form.serial_number} onChange={(value) => setForm((state) => ({ ...state, serial_number: value }))} />
              <Input label="Инвентаризационный №" value={form.inventory_number} onChange={(value) => setForm((state) => ({ ...state, inventory_number: value }))} />
              <Input label="ID терминала Русский Стандарт" value={form.terminal_id_rs} onChange={(value) => setForm((state) => ({ ...state, terminal_id_rs: value }))} />
              <Input label="ID терминала Сбер" value={form.terminal_id_sber} onChange={(value) => setForm((state) => ({ ...state, terminal_id_sber: value }))} />
              <Input label="Версия Windows" value={form.windows_version} onChange={(value) => setForm((state) => ({ ...state, windows_version: value }))} />
              <Input label="Номер по Розенцвайгу" value={form.rosenzweig_number} onChange={(value) => setForm((state) => ({ ...state, rosenzweig_number: value }))} />
              <Input label="Номер кассы" value={form.cash_number} onChange={(value) => setForm((state) => ({ ...state, cash_number: value }))} />
              <Input label="NetSupport" value={form.netsupport_target} onChange={(value) => setForm((state) => ({ ...state, netsupport_target: value }))} />
              <Input label="Второй экран" value={form.second_screen} onChange={(value) => setForm((state) => ({ ...state, second_screen: value }))} />
              <Input label="Статус ПИОТ" value={form.piot_status} onChange={(value) => setForm((state) => ({ ...state, piot_status: value }))} />
              <Input label="Денежный ящик" value={form.cash_drawer} onChange={(value) => setForm((state) => ({ ...state, cash_drawer: value }))} />
              <Input label="Статус терминала" value={form.terminal_status} onChange={(value) => setForm((state) => ({ ...state, terminal_status: value }))} />
              <label className="text-sm"><span className="mb-1 block text-slate-600">Тип ККМ</span><select className="app-input w-full px-3 py-2 text-sm" value={form.kkm_type} onChange={(event) => setForm((state) => ({ ...state, kkm_type: event.target.value as CashForm["kkm_type"] }))}><option value="retail">РИТЕЙЛ</option><option value="shtrih">ШТРИХ</option></select></label>
            </div>
            <label className="block text-sm"><span className="mb-1 block text-slate-600">Комментарий</span><textarea className="app-input min-h-20 w-full p-3 text-sm" value={form.comment} onChange={(event) => setForm((state) => ({ ...state, comment: event.target.value }))} /></label>
            <div className="flex justify-end gap-2"><button onClick={() => setIsModalOpen(false)} className="app-btn-secondary px-4 py-2 text-sm">Отмена</button><button onClick={submit} className="app-btn-primary px-4 py-2 text-sm">Сохранить</button></div>
          </div>
        </div>
      )}

      {(isFetching || createMut.isPending || updateMut.isPending) && <div className="fixed bottom-4 right-4 app-panel px-4 py-2 text-sm text-slate-600">Сохранение / обновление...</div>}
    </div>
  );
}

function CashRow({ item, isSuperuser, isPolling, onCopy, onPoll, onEdit, onDelete }: { item: CashRegister; isSuperuser: boolean; isPolling: boolean; onCopy: (value: string | null) => void; onPoll: () => void; onEdit: () => void; onDelete: () => void }) {
  return (
    <article className={`grid grid-cols-1 gap-4 p-4 lg:grid-cols-[minmax(12rem,1fr)_minmax(12rem,1.05fr)_minmax(15rem,1.35fr)_minmax(13rem,1fr)_auto] ${isAttention(item) ? "bg-amber-50/40" : ""}`}>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2"><div className="font-semibold text-slate-900">ККМ №{item.kkm_number}</div><StatusBadge item={item} /></div>
        <div className="flex flex-wrap gap-1.5"><Badge>{item.kkm_type === "retail" ? "РИТЕЙЛ" : "ШТРИХ"}</Badge>{item.cash_number && <Badge>касса {item.cash_number}</Badge>}{item.rosenzweig_number && <Badge>Розенцвайг {item.rosenzweig_number}</Badge>}</div>
        {item.terminal_status && <div className="flex items-center gap-1.5 text-xs font-medium text-rose-700"><AlertTriangle className="h-3.5 w-3.5" />{item.terminal_status}</div>}
      </div>

      <div className="space-y-2 text-sm"><SectionLabel>Сеть</SectionLabel><CopyValue value={item.hostname} onCopy={onCopy} /><Field label="NetSupport" value={item.netsupport_target} compact /><Field label="Последний опрос" value={item.last_polled_at ? new Date(item.last_polled_at).toLocaleString("ru-RU") : "ещё не было"} compact />{item.is_online === false && <div className="text-xs text-rose-600">{offlineReason(item.reachability_reason)}</div>}</div>

      <div className="space-y-2 text-sm"><SectionLabel>Терминалы и коды</SectionLabel><div className="grid grid-cols-2 gap-x-4 gap-y-1"><Field label="Код ТТ РС" value={item.store_code} compact /><Field label="Код ТТ Сбер" value={item.sber_store_code} compact /><Field label="ID РС" value={item.terminal_id_rs} compact /><Field label="ID Сбер" value={item.terminal_id_sber} compact /><Field label="Серийный" value={item.serial_number} compact /><Field label="Инв. №" value={item.inventory_number} compact /></div></div>

      <div className="space-y-2 text-sm"><SectionLabel>Оснащение</SectionLabel><div className="flex flex-wrap gap-1.5"><Badge tone={piotTone(item.piot_status)}>ПИОТ: {item.piot_status || "—"}</Badge><Badge tone={drawerTone(item.cash_drawer)}>Ящик: {item.cash_drawer || "—"}</Badge>{item.second_screen && <Badge tone="sky">2-й экран: {item.second_screen}</Badge>}<Badge>Windows {item.windows_version || "—"}</Badge></div>{item.comment && <div className="rounded-lg bg-white/80 px-2.5 py-2 text-xs text-slate-600 ring-1 ring-slate-200">{item.comment}</div>}</div>

      <div className="flex flex-wrap items-start gap-1.5 lg:w-28 lg:justify-end"><IconButton label="Скопировать hostname" onClick={() => onCopy(item.hostname)}><Copy className="h-4 w-4" /></IconButton><IconButton label="Обновить кассу" onClick={onPoll} disabled={isPolling}><RefreshCw className={`h-4 w-4 ${isPolling ? "animate-spin" : ""}`} /></IconButton>{isSuperuser && <><IconButton label="Редактировать кассу" onClick={onEdit}><Pencil className="h-4 w-4" /></IconButton><IconButton label="Удалить кассу" onClick={onDelete} danger><Trash2 className="h-4 w-4" /></IconButton></>}</div>
    </article>
  );
}

function StatusBadge({ item }: { item: CashRegister }) {
  if (item.is_online === true) return <Badge tone="green"><CircleCheck className="h-3.5 w-3.5" />online</Badge>;
  if (item.is_online === false) return <Badge tone="red"><CircleX className="h-3.5 w-3.5" />offline</Badge>;
  return <Badge><CircleHelp className="h-3.5 w-3.5" />не опрошена</Badge>;
}

function offlineReason(reason: CashRegister["reachability_reason"]) {
  if (reason === "dns_unresolved") return "Hostname не резолвится";
  if (reason === "port_closed") return "Сетевые порты недоступны";
  return "Хост недоступен";
}

function piotTone(value: string | null): BadgeTone {
  const normalized = (value || "").toLocaleUpperCase("ru-RU");
  if (!normalized) return "default";
  return normalized.includes("НЕ ОБНОВЛЕН") || !normalized.includes("ОБНОВЛЕН") ? "red" : "green";
}

function drawerTone(value: string | null): BadgeTone {
  if (!value) return "default";
  return value.trim().toLocaleLowerCase("ru-RU") === "да" ? "green" : "amber";
}

function CopyValue({ value, onCopy }: { value: string | null; onCopy: (value: string | null) => void }) {
  return <div className="flex items-center gap-1.5"><span className="font-medium text-slate-800">{value || "—"}</span>{value && <button onClick={() => onCopy(value)} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-rose-600" title="Скопировать"><Copy className="h-3.5 w-3.5" /></button>}</div>;
}

function Field({ label, value, compact = false }: { label: string; value: string | null; compact?: boolean }) {
  return <div className={compact ? "text-xs" : "text-sm"}><span className="text-slate-400">{label}: </span><span className="text-slate-700">{value || "—"}</span></div>;
}

function SectionLabel({ children }: { children: string }) { return <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{children}</div>; }

type BadgeTone = "default" | "green" | "red" | "amber" | "sky" | "violet";
const badgeTone: Record<BadgeTone, string> = { default: "bg-slate-100 text-slate-600", green: "bg-emerald-100 text-emerald-700", red: "bg-rose-100 text-rose-700", amber: "bg-amber-100 text-amber-800", sky: "bg-sky-100 text-sky-700", violet: "bg-violet-100 text-violet-700" };
function Badge({ children, tone = "default" }: { children: ReactNode; tone?: BadgeTone }) { return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium ${badgeTone[tone]}`}>{children}</span>; }

function IconButton({ label, onClick, children, disabled = false, danger = false }: { label: string; onClick: () => void; children: ReactNode; disabled?: boolean; danger?: boolean }) { return <button type="button" onClick={onClick} disabled={disabled} aria-label={label} title={label} className={`app-btn-secondary inline-flex h-9 w-9 items-center justify-center disabled:opacity-40 ${danger ? "text-rose-600" : ""}`}>{children}</button>; }

function FilterSelect({ label, value, onChange, children }: { label: string; value: string; onChange: (value: string) => void; children: ReactNode }) { return <label className="text-xs text-slate-500"><span className="mb-1 block">{label}</span><select className="app-input w-full px-3 py-2 text-sm text-slate-700" value={value} onChange={(event) => onChange(event.target.value)}>{children}</select></label>; }

function Input({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="text-sm"><span className="mb-1 block text-slate-600">{label}</span><input className="app-input w-full px-3 py-2 text-sm" value={value} onChange={(event) => onChange(event.target.value)} /></label>; }

function Stat({ label, value, active, onClick, tone = "default" }: { label: string; value: number; active: boolean; onClick: () => void; tone?: BadgeTone }) { const ring = tone === "green" ? "ring-emerald-400/60" : tone === "red" ? "ring-rose-400/60" : tone === "amber" ? "ring-amber-400/60" : tone === "sky" ? "ring-sky-400/60" : tone === "violet" ? "ring-violet-400/60" : "ring-slate-400/50"; return <button onClick={onClick} className={`app-stat px-4 py-3 text-left transition ${active ? `ring-2 ${ring}` : "hover:shadow-sm"}`} type="button"><div className="text-2xl font-bold text-gray-900">{value}</div><div className="mt-0.5 text-xs text-gray-500">{label}</div></button>; }
