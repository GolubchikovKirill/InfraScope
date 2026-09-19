import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import type { CashRegister } from "../../client";
import { cashState, groupByZoneAndStore, isAttention, storeLabel, tileLabel, type CashState } from "../../lib/cashRegisters";

const TILE_STYLE: Record<CashState, string> = {
  online:
    "border-teal-200 bg-teal-100 text-teal-900 hover:bg-teal-200 dark:border-teal-800 dark:bg-teal-900/50 dark:text-teal-50 dark:hover:bg-teal-800/60",
  offline:
    "border-slate-600 bg-slate-600 text-white hover:bg-slate-700 dark:border-slate-500 dark:bg-slate-500 dark:hover:bg-slate-400",
  unknown:
    "border-dashed border-slate-300 bg-slate-50 text-slate-500 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-slate-800",
};

const STATE_WORD: Record<CashState, string> = { online: "на связи", offline: "недоступна", unknown: "нет данных" };

function Legend() {
  const dot = "inline-block h-3 w-3 rounded-[3px] border";
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400" aria-label="Обозначения">
      <li className="inline-flex items-center gap-1.5"><span className={`${dot} ${TILE_STYLE.online}`} />на связи</li>
      <li className="inline-flex items-center gap-1.5"><span className={`${dot} ${TILE_STYLE.offline}`} />недоступна</li>
      <li className="inline-flex items-center gap-1.5"><span className={`${dot} ${TILE_STYLE.unknown}`} />нет данных</li>
      <li className="inline-flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-full bg-amber-400" />есть замечание</li>
    </ul>
  );
}

function Tile({ register, onSelect }: { register: CashRegister; onSelect: (id: string) => void }) {
  const state = cashState(register);
  const attention = isAttention(register);
  const label = `${register.hostname}, ${storeLabel(register.store_number)}, ${STATE_WORD[state]}${attention ? ", есть замечание" : ""}`;
  return (
    <button
      type="button"
      onClick={() => onSelect(register.id)}
      title={label}
      aria-label={label}
      className={`relative flex h-11 min-w-0 items-center justify-center rounded-md border text-sm font-semibold tabular-nums transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] ${TILE_STYLE[state]}`}
    >
      {tileLabel(register.hostname)}
      {attention && <span aria-hidden="true" className="absolute right-1 top-1 h-2 w-2 rounded-full bg-amber-400 ring-1 ring-white/70" />}
    </button>
  );
}

/** Availability of every register at a glance, grouped zone -> store like a Grafana
 *  state-timeline panel. A tile opens the quick-look drawer (see CashRegisterDrawer). */
export default function CashRegisterMap({
  rows,
  isLoading,
  onSelect,
}: {
  rows: CashRegister[];
  isLoading: boolean;
  onSelect: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [onlyProblems, setOnlyProblems] = useState(false);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (onlyProblems && cashState(row) === "online" && !isAttention(row)) return false;
      if (!needle) return true;
      return [row.hostname, row.kkm_number, storeLabel(row.store_number)].some((v) => (v ?? "").toLowerCase().includes(needle));
    });
  }, [rows, query, onlyProblems]);
  const zones = useMemo(() => groupByZoneAndStore(visible), [visible]);

  const total = rows.length;
  const online = rows.filter((r) => cashState(r) === "online").length;

  return (
    <section aria-labelledby="cash-map-title" className="app-panel overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-[var(--app-panel-border)] px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 id="cash-map-title" className="font-semibold text-slate-900 dark:text-slate-100">Кассы</h3>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
            {total ? `${online} из ${total} на связи. Нажмите на кассу — краткая информация и подключение.` : "Нет касс для отображения."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative">
            <span className="sr-only">Найти кассу</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Касса или магазин"
              className="app-input w-52 py-1.5 pl-8 pr-2 text-sm"
            />
          </label>
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />
            Только с замечаниями
          </label>
        </div>
      </div>

      <div className="space-y-6 px-5 py-4">
        <Legend />

        {isLoading && !rows.length ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
            {Array.from({ length: 10 }).map((_, i) => <div key={i} className="app-skeleton h-24" />)}
          </div>
        ) : !zones.length ? (
          <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">
            {rows.length ? "По этому запросу касс нет." : "Кассы ещё не добавлены."}
          </p>
        ) : (
          zones.map((zone) => (
            <div key={zone.zone} data-testid={`zone-${zone.zone}`}>
              <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{zone.label}</h4>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {zone.total} касс · {zone.online} на связи
                  {zone.offline > 0 && ` · ${zone.offline} недоступны`}
                  {zone.unknown > 0 && ` · ${zone.unknown} без данных`}
                  {zone.attention > 0 && ` · ${zone.attention} с замечаниями`}
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
                {zone.stores.map((store) => {
                  const storeOnline = store.rows.filter((r) => cashState(r) === "online").length;
                  return (
                    <div
                      key={store.key}
                      data-testid={`store-${store.key}`}
                      className="rounded-xl border border-[var(--app-panel-border)] bg-[var(--app-panel-bg)] p-3"
                    >
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <p className="truncate text-sm font-medium text-slate-800 dark:text-slate-100" title={store.label}>{store.label}</p>
                        <span
                          className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold tabular-nums ${
                            storeOnline === store.rows.length
                              ? "bg-teal-50 text-teal-800 dark:bg-teal-950/40 dark:text-teal-200"
                              : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                          }`}
                        >
                          {storeOnline}/{store.rows.length}
                        </span>
                      </div>
                      <div className="grid grid-cols-[repeat(auto-fill,minmax(3.4rem,1fr))] gap-1.5">
                        {store.rows.map((row) => <Tile key={row.id} register={row} onSelect={onSelect} />)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
