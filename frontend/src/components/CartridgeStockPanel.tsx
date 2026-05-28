import { useState } from "react";
import { History, Minus, RefreshCw, Save } from "lucide-react";
import type { CartridgeStock, CartridgeStockMovement } from "../client";

interface Props {
  rows: CartridgeStock[];
  movements?: CartridgeStockMovement[];
  loading: boolean;
  syncing: boolean;
  savingId?: string | null;
  selectedId?: string | null;
  isSuperuser: boolean;
  onSync: () => void;
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
  syncing,
  savingId,
  selectedId,
  isSuperuser,
  onSync,
  onSelect,
  onAdjust,
  onIssue,
}: Props) {
  const [drafts, setDrafts] = useState<Record<string, { quantity: string; minimum: string }>>({});

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
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-sm font-semibold text-gray-900">Склад картриджей</div>
            <div className="text-xs text-gray-500">Позиции собираются из моделей картриджей в карточках принтеров</div>
          </div>
          {isSuperuser && (
            <button
              type="button"
              onClick={onSync}
              disabled={syncing}
              className="app-btn-primary inline-flex w-fit items-center gap-2 px-4 py-2 text-sm disabled:opacity-50"
            >
              <RefreshCw className={`size-4 ${syncing ? "animate-spin" : ""}`} />
              {syncing ? "Синхронизация..." : "Синхронизировать"}
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="app-panel p-8 text-center text-gray-500">Загрузка...</div>
      ) : rows.length === 0 ? (
        <div className="app-panel p-8 text-center text-gray-500">
          <div className="text-base font-medium text-gray-700">Склад пока пуст</div>
          <div className="mt-1 text-sm">Заполните наименования картриджей в принтерах и нажмите синхронизацию</div>
        </div>
      ) : (
        <div className="app-panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-100 text-sm">
              <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-3">Картридж</th>
                  <th className="px-4 py-3">Цвет</th>
                  <th className="px-4 py-3">Принтеры</th>
                  <th className="px-4 py-3">Остаток</th>
                  <th className="px-4 py-3">Минимум</th>
                  <th className="px-4 py-3 text-right">Действия</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {rows.map((row) => {
                  const draft = draftFor(row);
                  const low = row.quantity_on_hand <= row.minimum_stock;
                  return (
                    <tr key={row.id} className={low ? "bg-amber-50/70" : "bg-white"}>
                      <td className="px-4 py-3">
                        <div className="font-medium text-gray-900">{row.cartridge_name}</div>
                        <div className="text-xs text-gray-500">{row.printer_count} принт.</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-flex min-w-7 justify-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
                          {colorLabel(row.toner_color)}
                        </span>
                      </td>
                      <td className="max-w-xs px-4 py-3 text-xs text-gray-500">
                        <div className="line-clamp-2" title={row.compatible_printer_models}>
                          {row.compatible_printer_models || "—"}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <input
                          value={draft.quantity}
                          onChange={(event) => updateDraft(row.id, { quantity: event.target.value })}
                          disabled={!isSuperuser}
                          inputMode="numeric"
                          className="app-input w-20 px-2 py-1 text-sm tabular-nums disabled:bg-gray-50"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <input
                          value={draft.minimum}
                          onChange={(event) => updateDraft(row.id, { minimum: event.target.value })}
                          disabled={!isSuperuser}
                          inputMode="numeric"
                          className="app-input w-20 px-2 py-1 text-sm tabular-nums disabled:bg-gray-50"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => onSelect(row.id)}
                            className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
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
                                className="rounded-lg p-1.5 text-gray-500 hover:bg-emerald-50 hover:text-emerald-700 disabled:opacity-50"
                                title="Сохранить остаток"
                                aria-label="Сохранить остаток"
                              >
                                <Save className="size-4" />
                              </button>
                              <button
                                type="button"
                                onClick={() => onIssue(row.id)}
                                disabled={savingId === row.id || row.quantity_on_hand <= 0}
                                className="rounded-lg p-1.5 text-gray-500 hover:bg-rose-50 hover:text-rose-700 disabled:opacity-40"
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
        </div>
      )}

      {selectedId && movements.length > 0 && (
        <div className="app-panel p-4">
          <div className="text-sm font-semibold text-gray-900">Последние движения</div>
          <div className="mt-3 grid gap-2">
            {movements.map((movement) => (
              <div key={movement.id} className="flex items-center justify-between gap-3 rounded-lg bg-gray-50 px-3 py-2 text-xs">
                <span className={movement.delta < 0 ? "font-medium text-rose-700" : "font-medium text-emerald-700"}>
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

function Summary({ label, value, tone = "default" }: { label: string; value: number; tone?: "default" | "warn" }) {
  return (
    <div className={`app-stat px-4 py-3 ${tone === "warn" ? "bg-amber-50" : "bg-gray-100"}`}>
      <div className={`text-2xl font-bold tabular-nums ${tone === "warn" ? "text-amber-700" : "text-gray-900"}`}>{value}</div>
      <div className="mt-0.5 text-xs text-gray-500">{label}</div>
    </div>
  );
}
