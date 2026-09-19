import type { CashState } from "../../lib/cashRegisters";
import type { TileView, ZoneView } from "../../lib/storeView";

const TILE_STYLE: Record<CashState, string> = {
  online:
    "border-teal-200 bg-teal-100 text-teal-900 hover:bg-teal-200 dark:border-teal-800 dark:bg-teal-900/50 dark:text-teal-50 dark:hover:bg-teal-800/60",
  offline:
    "border-slate-600 bg-slate-600 text-white hover:bg-slate-700 dark:border-slate-500 dark:bg-slate-500 dark:hover:bg-slate-400",
  unknown:
    "border-dashed border-slate-300 bg-slate-50 text-slate-500 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-slate-800",
};

export function Legend({ withRemarks }: { withRemarks: boolean }) {
  const dot = "inline-block h-3 w-3 rounded-[3px] border";
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400" aria-label="Обозначения">
      <li className="inline-flex items-center gap-1.5"><span className={`${dot} ${TILE_STYLE.online}`} />на связи</li>
      <li className="inline-flex items-center gap-1.5"><span className={`${dot} ${TILE_STYLE.offline}`} />недоступно</li>
      <li className="inline-flex items-center gap-1.5"><span className={`${dot} ${TILE_STYLE.unknown}`} />нет данных</li>
      {withRemarks && <li className="inline-flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-full bg-amber-400" />есть замечание</li>}
    </ul>
  );
}

function Tile({ tile, onSelect }: { tile: TileView; onSelect: (id: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(tile.id)}
      title={tile.aria}
      aria-label={tile.aria}
      className={`relative flex h-11 min-w-0 flex-col items-center justify-center rounded-md border px-0.5 font-semibold tabular-nums leading-tight transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] ${TILE_STYLE[tile.state]}`}
    >
      {tile.top && <span className="text-[9px] font-medium uppercase tracking-wide opacity-70">{tile.top}</span>}
      <span className="max-w-full truncate text-sm">{tile.label}</span>
      {tile.attention && <span aria-hidden="true" className="absolute right-1 top-1 h-2 w-2 rounded-full bg-amber-400 ring-1 ring-white/70" />}
    </button>
  );
}

/** Zones of store panels of tiles - the same picture for every device kind. */
export default function StoreGrid({ zones, onSelect, noun }: { zones: ZoneView[]; onSelect: (id: string) => void; noun: string }) {
  return (
    <>
      {zones.map((zone) => (
        <div key={zone.key} data-testid={`zone-${zone.key}`}>
          <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{zone.label}</h4>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {zone.total} {noun} · {zone.online} на связи
              {zone.offline > 0 && ` · ${zone.offline} недоступны`}
              {zone.unknown > 0 && ` · ${zone.unknown} без данных`}
              {zone.attention > 0 && ` · ${zone.attention} с замечаниями`}
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
            {zone.stores.map((store) => {
              const online = store.tiles.filter((t) => t.state === "online").length;
              return (
                <div key={store.key} data-testid={`store-${store.key}`} className="rounded-xl border border-[var(--app-panel-border)] bg-[var(--app-panel-bg)] p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium text-slate-800 dark:text-slate-100" title={store.title}>{store.title}</p>
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold tabular-nums ${
                        online === store.tiles.length
                          ? "bg-teal-50 text-teal-800 dark:bg-teal-950/40 dark:text-teal-200"
                          : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                      }`}
                    >
                      {online}/{store.tiles.length}
                    </span>
                  </div>
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(3.4rem,1fr))] gap-1.5">
                    {store.tiles.map((tile) => <Tile key={tile.id} tile={tile} onSelect={onSelect} />)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </>
  );
}
