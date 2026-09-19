import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import type { CashRegister, Computer } from "../../client";
import { cashState, isAttention, storeLabel } from "../../lib/cashRegisters";
import { buildStoreIndex, cashView, computerView } from "../../lib/storeView";
import { storeCode } from "../../lib/stores";
import StoreGrid, { Legend } from "./StoreGrid";

type Kind = "cash" | "computers";

const TABS: Array<{ id: Kind; label: string }> = [
  { id: "cash", label: "Кассы" },
  { id: "computers", label: "Компьютеры" },
];

const count = (rows: Array<{ is_online: boolean | null }>) => `${rows.filter((r) => r.is_online === true).length}/${rows.length}`;

/** Availability of the shop equipment at a glance, grouped zone -> store like a Grafana
 *  state-timeline panel, one tab per kind. A tile opens the quick-look drawer. */
export default function FleetMap({
  cashRegisters,
  computers,
  remoteLocation,
  isLoading,
  onSelect,
}: {
  cashRegisters: CashRegister[];
  computers: Computer[];
  /** the location kept on a host's RustDesk entry, used when the computer has none */
  remoteLocation: (hostname: string) => string | null | undefined;
  isLoading: boolean;
  onSelect: (kind: Kind, id: string) => void;
}) {
  const [kind, setKind] = useState<Kind>("cash");
  const [query, setQuery] = useState("");
  const [onlyProblems, setOnlyProblems] = useState(false);

  const storeIndex = useMemo(() => buildStoreIndex(cashRegisters), [cashRegisters]);

  const zones = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (kind === "cash") {
      const rows = cashRegisters.filter((row) => {
        if (onlyProblems && cashState(row) === "online" && !isAttention(row)) return false;
        return !needle || [row.hostname, row.kkm_number, storeLabel(row.store_number)].some((v) => (v ?? "").toLowerCase().includes(needle));
      });
      return cashView(rows);
    }
    // a computer is matched on its own fields; the store text is matched after grouping
    const all = computerView(computers, { storeIndex, remoteLocation });
    const wanted = new Set<string>();
    for (const zone of all) {
      for (const store of zone.stores) {
        const storeHit = needle && [store.label, store.title, storeCode(store.label) ?? ""].some((v) => v.toLowerCase().includes(needle));
        for (const tile of store.tiles) {
          if (onlyProblems && tile.state === "online") continue;
          if (!needle || storeHit || tile.hostname.toLowerCase().includes(needle)) wanted.add(tile.id);
        }
      }
    }
    return computerView(
      computers.filter((c) => wanted.has(c.id)),
      { storeIndex, remoteLocation },
    );
  }, [kind, cashRegisters, computers, query, onlyProblems, storeIndex, remoteLocation]);

  const rows = kind === "cash" ? cashRegisters : computers;
  const noun = kind === "cash" ? "касс" : "компьютеров";
  const summary = rows.length
    ? `${count(rows)} на связи. Нажмите — краткая информация и подключение.`
    : kind === "cash" ? "Кассы ещё не добавлены." : "Компьютеры ещё не добавлены.";

  return (
    <section aria-labelledby="fleet-map-title" className="app-panel overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-[var(--app-panel-border)] px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h3 id="fleet-map-title" className="font-semibold text-slate-900 dark:text-slate-100">По магазинам</h3>
            <div role="tablist" aria-label="Тип техники" className="inline-flex rounded-lg border border-[var(--app-panel-border)] p-0.5">
              {TABS.map((tab) => {
                const active = tab.id === kind;
                return (
                  <button
                    key={tab.id}
                    role="tab"
                    type="button"
                    aria-selected={active}
                    onClick={() => setKind(tab.id)}
                    className={`rounded-md px-3 py-1 text-sm font-medium transition ${
                      active
                        ? "bg-[var(--brand)] text-white"
                        : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                    }`}
                  >
                    {tab.label}
                    <span className={`ml-1.5 text-xs tabular-nums ${active ? "text-white/80" : "text-slate-400"}`}>
                      {count(tab.id === "cash" ? cashRegisters : computers)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{summary}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative">
            <span className="sr-only">Найти</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={kind === "cash" ? "Касса или магазин" : "Компьютер или магазин"}
              className="app-input w-52 py-1.5 pl-8 pr-2 text-sm"
            />
          </label>
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />
            Только проблемные
          </label>
        </div>
      </div>

      <div className="space-y-6 px-5 py-4" role="tabpanel">
        <Legend withRemarks={kind === "cash"} />

        {isLoading && !rows.length ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
            {Array.from({ length: 10 }).map((_, i) => <div key={i} className="app-skeleton h-24" />)}
          </div>
        ) : !zones.length ? (
          <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">
            {rows.length ? "По этому запросу ничего нет." : kind === "cash" ? "Кассы ещё не добавлены." : "Компьютеры ещё не добавлены."}
          </p>
        ) : (
          <StoreGrid zones={zones} noun={noun} onSelect={(id) => onSelect(kind, id)} />
        )}
      </div>
    </section>
  );
}
