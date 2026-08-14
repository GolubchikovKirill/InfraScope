import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, History, Minus, Save } from "lucide-react";
import type { CartridgeStock, CartridgeStockMovement } from "../client";

type SortKey = "name" | "color" | "printers" | "quantity" | "minimum";
type SortDir = "asc" | "desc";

const COLOR_ORDER: Record<string, number> = { black: 0, cyan: 1, magenta: 2, yellow: 3 };

function compareRows(a: CartridgeStock, b: CartridgeStock, key: SortKey): number {
  switch (key) {
    case "color":
      return (COLOR_ORDER[a.toner_color ?? ""] ?? 99) - (COLOR_ORDER[b.toner_color ?? ""] ?? 99);
    case "printers":
      // The cartridge catalog is maintained by hand now (see onSync removal),
      // so printer_count never gets populated - sort by what this column
      // actually displays (the compatible-models text) instead of a field
      // that would otherwise permanently tie everything at 0.
      return (a.compatible_printer_models || "").localeCompare(b.compatible_printer_models || "", "ru");
    case "quantity":
      return a.quantity_on_hand - b.quantity_on_hand;
    case "minimum":
      return a.minimum_stock - b.minimum_stock;
    case "name":
    default:
      return a.cartridge_name.localeCompare(b.cartridge_name, "ru");
  }
}

interface Props {
  rows: CartridgeStock[];
  movements?: CartridgeStockMovement[];
  loading: boolean;
  savingId?: string | null;
  selectedId?: string | null;
  isSuperuser: boolean;
  onSelect: (id: string) => void;
  onAdjust: (id: string, quantity: number, minimum: number) => void;
  onIssue: (id: string) => void;
}

function colorLabel(value: string | null): string {
  if (value === "black") return "K";
  if (value === "cyan") return "C";
  if (value === "magenta") return "M";
  if (value === "yellow") return "Y";
  return "—";
}

function movementLabel(reason: string): string {
  if (reason === "issue") return "выдача";
  if (reason === "adjust") return "корректировка";
  return reason;
}

export default function CartridgeStockPanel({
  rows,
  movements = [],
  loading,
  savingId,
  selectedId,
  isSuperuser,
  onSelect,
  onAdjust,
  onIssue,
}: Props) {
  const [drafts, setDrafts] = useState<Record<string, { quantity: string; minimum: string }>>({});
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((dir) => (dir === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const sortedRows = useMemo(() => {
    const sorted = [...rows].sort((a, b) => compareRows(a, b, sortKey));
    return sortDir === "asc" ? sorted : sorted.reverse();
  }, [rows, sortKey, sortDir]);

  const draftFor = (row: CartridgeStock) => drafts[row.id] ?? {
    quantity: String(row.quantity_on_hand),
    minimum: String(row.minimum_stock),
  };

  const updateDraft = (id: string, patch: Partial<{ quantity: string; minimum: string }>) => {
    setDrafts((current) => ({
      ...current,
      [id]: {
        quantity: current[id]?.quantity ?? String(rows.find((row) => row.id === id)?.quantity_on_hand ?? 0),
        minimum: current[id]?.minimum ?? String(rows.find((row) => row.id === id)?.minimum_stock ?? 0),
        ...patch,
      },
    }));
  };

  const saveDraft = (row: CartridgeStock) => {
    const draft = draftFor(row);
    const quantity = Math.max(0, Number.parseInt(draft.quantity || "0", 10));
    const minimum = Math.max(0, Number.parseInt(draft.minimum || "0", 10));
    onAdjust(row.id, quantity, minimum);
  };

  const totalStock = rows.reduce((sum, row) => sum + row.quantity_on_hand, 0);
  const lowCount = rows.filter((row) => row.quantity_on_hand <= row.minimum_stock).length;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 grid-cols-3">
        <Summary label="Позиций" value={rows.length} />
        <Summary label="На складе" value={totalStock} />
        <Summary label="Низкий остаток" value={lowCount} tone="warn" />
      </div>

      <div className="app-panel p-3">
        <div className="text-sm font-semibold text-gray-900">Склад картриджей</div>
        <div className="text-xs text-gray-500">Остатки и совместимость ведутся вручную по инвентаризации</div>
      </div>

      {loading ? (
        <div className="app-panel p-8 text-center text-gray-500">Загрузка...</div>
      ) : rows.length === 0 ? (
        <div className="app-panel p-8 text-center text-gray-500">
          <div className="text-base font-medium text-gray-700">Склад пока пуст</div>
        </div>
      ) : (
        <div className="app-table-wrap">
          <table className="app-table min-w-full">
            <thead>
              <tr>
                <SortableHeader label="Картридж" sortKey="name" active={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortableHeader label="Цвет" sortKey="color" active={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortableHeader label="Принтеры" sortKey="printers" active={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortableHeader label="Остаток" sortKey="quantity" active={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortableHeader label="Минимум" sortKey="minimum" active={sortKey} dir={sortDir} onSort={toggleSort} />
                <th className="text-right">Действия</th>
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row) => {
                const draft = draftFor(row);
                const low = row.quantity_on_hand <= row.minimum_stock;
                return (
                  <tr key={row.id} className={low ? "bg-[var(--warn-bg)]" : undefined}>
                    <td>
                      <div className="app-card-title">{row.cartridge_name}</div>
                    </td>
                    <td>
                      <span className="inline-flex min-w-7 justify-center rounded-full bg-[var(--surface-3)] px-2 py-0.5 text-xs font-medium text-[var(--text-default)]">
                        {colorLabel(row.toner_color)}
                      </span>
                    </td>
                    <td className="max-w-xs app-card-meta">
                      <div className="line-clamp-2" title={row.compatible_printer_models}>
                        {row.compatible_printer_models || "—"}
                      </div>
                    </td>
                    <td>
                      <input
                        value={draft.quantity}
                        onChange={(event) => updateDraft(row.id, { quantity: event.target.value })}
                        disabled={!isSuperuser}
                        inputMode="numeric"
                        className="app-input w-20 px-2 py-1 text-sm tabular-nums disabled:bg-[var(--surface-2)]"
                      />
                    </td>
                    <td>
                      <input
                        value={draft.minimum}
                        onChange={(event) => updateDraft(row.id, { minimum: event.target.value })}
                        disabled={!isSuperuser}
                        inputMode="numeric"
                        className="app-input w-20 px-2 py-1 text-sm tabular-nums disabled:bg-[var(--surface-2)]"
                      />
                    </td>
                    <td>
                      <div className="flex justify-end gap-1">
                        <button
                          type="button"
                          onClick={() => onSelect(row.id)}
                          className="app-icon-btn text-[var(--text-faint)] hover:bg-[var(--surface-2)] hover:text-[var(--text-default)]"
                          title="История"
                          aria-label="История движений"
                        >
                          <History className="size-4" />
                        </button>
                        {isSuperuser && (
                          <>
                            <button
                              type="button"
                              onClick={() => saveDraft(row)}
                              disabled={savingId === row.id}
                              className="app-icon-btn text-[var(--text-faint)] hover:bg-[var(--ok-bg)] hover:text-[var(--ok-fg)] disabled:opacity-50"
                              title="Сохранить остаток"
                              aria-label="Сохранить остаток"
                            >
                              <Save className="size-4" />
                            </button>
                            <button
                              type="button"
                              onClick={() => onIssue(row.id)}
                              disabled={savingId === row.id || row.quantity_on_hand <= 0}
                              className="app-icon-btn text-[var(--text-faint)] hover:bg-[var(--danger-bg)] hover:text-[var(--danger-fg)] disabled:opacity-40"
                              title="Выдать 1 картридж"
                              aria-label="Выдать 1 картридж"
                            >
                              <Minus className="size-4" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {selectedId && movements.length > 0 && (
        <div className="app-panel p-4">
          <div className="text-sm font-semibold text-gray-900">Последние движения</div>
          <div className="mt-3 grid gap-2">
            {movements.map((movement) => (
              <div key={movement.id} className="flex items-center justify-between gap-3 rounded-lg bg-gray-50 px-3 py-2 text-xs">
                <span className={movement.delta < 0 ? "font-medium text-[var(--danger-fg)]" : "font-medium text-emerald-700"}>
                  {movement.delta > 0 ? "+" : ""}{movement.delta}
                </span>
                <span className="flex-1 text-gray-600">{movementLabel(movement.reason)}{movement.note ? `: ${movement.note}` : ""}</span>
                <span className="text-gray-400">
                  {new Date(movement.created_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function SortableHeader({
  label,
  sortKey: key,
  active,
  dir,
  onSort,
}: {
  label: string;
  sortKey: SortKey;
  active: SortKey;
  dir: SortDir;
  onSort: (key: SortKey) => void;
}) {
  const isActive = active === key;
  const Icon = isActive ? (dir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  return (
    <th>
      <button
        type="button"
        onClick={() => onSort(key)}
        className={`inline-flex items-center gap-1 transition hover:text-[var(--text-strong)] ${
          isActive ? "text-[var(--text-strong)] font-semibold" : ""
        }`}
      >
        {label}
        <Icon className={`size-3 ${isActive ? "" : "text-[var(--text-faint)]"}`} />
      </button>
    </th>
  );
}

function Summary({ label, value, tone = "default" }: { label: string; value: number; tone?: "default" | "warn" }) {
  return (
    <div className={`app-stat px-4 py-3 ${tone === "warn" ? "bg-amber-50" : "bg-gray-100"}`}>
      <div className={`text-2xl font-bold tabular-nums ${tone === "warn" ? "text-amber-700" : "text-gray-900"}`}>{value}</div>
      <div className="mt-0.5 text-xs text-gray-500">{label}</div>
    </div>
  );
}
