import type { CashRegister, Computer } from "../client";
import { cashState, groupByZoneAndStore, isAttention, storeLabel, tileLabel, type CashState } from "./cashRegisters";
import { storeCode, storeTitle } from "./stores";

/** What the overview map draws, whatever the device kind: zones of store panels of tiles. */
export type TileView = {
  id: string;
  state: CashState;
  /** a remark on a device that otherwise answers (cash registers only) */
  attention: boolean;
  /** small caption above the label (the role token of a computer: MGR, TV, ...) */
  top: string | null;
  label: string;
  aria: string;
  hostname: string;
};

export type StoreView = { key: string; label: string; title: string; tiles: TileView[] };

export type ZoneView = {
  key: string;
  label: string;
  stores: StoreView[];
  total: number;
  online: number;
  offline: number;
  unknown: number;
  attention: number;
};

const STATE_WORD: Record<CashState, string> = { online: "на связи", offline: "недоступна", unknown: "нет данных" };
const COMPUTER_STATE_WORD: Record<CashState, string> = { online: "на связи", offline: "недоступен", unknown: "нет данных" };

const compareText = (a: string, b: string) => a.localeCompare(b, "ru", { numeric: true, sensitivity: "base" });

function makeZone(key: string, label: string, stores: StoreView[]): ZoneView {
  const tiles = stores.flatMap((s) => s.tiles);
  return {
    key,
    label,
    stores,
    total: tiles.length,
    online: tiles.filter((t) => t.state === "online").length,
    offline: tiles.filter((t) => t.state === "offline").length,
    unknown: tiles.filter((t) => t.state === "unknown").length,
    attention: tiles.filter((t) => t.attention).length,
  };
}

export function cashView(rows: CashRegister[]): ZoneView[] {
  return groupByZoneAndStore(rows).map((zone) =>
    makeZone(
      zone.zone,
      zone.label,
      zone.stores.map((store) => ({
        key: store.key,
        label: store.label,
        title: storeTitle(store.label),
        tiles: store.rows.map((row) => {
          const state = cashState(row);
          const attention = isAttention(row);
          return {
            id: row.id,
            state,
            attention,
            top: null,
            label: tileLabel(row.hostname),
            hostname: row.hostname,
            aria: `${row.hostname}, ${storeLabel(row.store_number)}, ${STATE_WORD[state]}${attention ? ", есть замечание" : ""}`,
          };
        }),
      })),
    ),
  );
}

// ---------------------------------------------------------------- computers

/** Store code out of a hostname, when the name carries one. VNA-MGR-205 -> A2,
 *  VNA-MGR-1505 -> A15, VNA-MGR-3002 -> A30 (the digits before the last two are the store
 *  number, the last two are the machine in it), VN3-... -> VN3, VND-... -> D1, and the
 *  spelled-out forms VNK-EGAISA15 / VNA-TV-A9N11. Anything else is left for a person. */
export function hostnameStoreCode(hostname: string): string | null {
  const name = hostname.trim().toUpperCase();
  const m = /^(VN[A-Z0-9])-([A-Z]+)-?(.+)$/.exec(name);
  if (!m) return null;
  const [, site, , suffix] = m;
  if (site === "VN3") return "VN3";
  if (site === "VND") return "D1";

  const numeric = /^(\d{3,4})[A-Z]*$/.exec(suffix);
  if (numeric) {
    const digits = numeric[1].replace(/^0+/, "");
    return digits.length >= 3 ? `A${digits.slice(0, -2)}` : null;
  }
  // the store spelled into the name: EGAISA15, TV-A9N11, SEC-A2 (tested on everything after "VNx-")
  const spelled = /^(?:EGAIS|[A-Z]+-)?A(\d{1,2})(?:N[A-Z]*\d+)?$/.exec(name.slice(4));
  return spelled ? `A${spelled[1]}` : null;
}

/** MGR / TV / SEC ... and the rest of the name, for a small tile. */
export function computerTile(hostname: string): { type: string | null; id: string } {
  const m = /^VN[A-Z0-9]-([A-Z]+)-?(.+)$/i.exec(hostname.trim());
  if (!m) return { type: null, id: hostname.trim().slice(-6) || "—" };
  return { type: m[1].toUpperCase(), id: m[2] };
}

export type StoreIndex = Map<string, { label: string; zoneKey: string; zoneLabel: string }>;

/** Store code -> the label and zone the cash registers already give that store. */
export function buildStoreIndex(cash: CashRegister[]): StoreIndex {
  const index: StoreIndex = new Map();
  for (const zone of groupByZoneAndStore(cash)) {
    for (const store of zone.stores) {
      const code = storeCode(store.label);
      if (code && !index.has(code)) index.set(code, { label: store.label, zoneKey: zone.zone, zoneLabel: zone.label });
    }
  }
  return index;
}

const OTHER_STORES = { key: "stores", label: "Другие магазины" };
const OFFICE = { key: "office", label: "Офис и служебные" };
const UNKNOWN = { key: "unknown", label: "Магазин не определён" };
const ZONE_ORDER = ["DF", "DP", OTHER_STORES.key, OFFICE.key, UNKNOWN.key];

type Placement = { zone: { key: string; label: string }; label: string; key: string };
type PlaceContext = { storeIndex: StoreIndex; remoteLocation: (hostname: string) => string | null | undefined };

/** Where a computer belongs on the map. The store comes from the record when it has one
 *  (location, or the location on its RustDesk entry), else from the hostname. VNK-*
 *  machines that name no store are office/service equipment, grouped by role; other
 *  unplaced machines wait in "Магазин не определён". */
export function placeComputer(row: Pick<Computer, "hostname" | "location">, ctx: PlaceContext): Placement {
  const code = storeCode(row.location) ?? storeCode(ctx.remoteLocation(row.hostname)) ?? hostnameStoreCode(row.hostname);
  if (code) {
    const known = ctx.storeIndex.get(code);
    const zone = known ? { key: known.zoneKey, label: known.zoneLabel } : OTHER_STORES;
    return { zone, label: known?.label ?? code, key: `${zone.key}:${code}` };
  }
  if (row.hostname.toUpperCase().startsWith("VNK-")) {
    const label = computerTile(row.hostname).type ?? "Прочее";
    return { zone: OFFICE, label, key: `${OFFICE.key}:${label}` };
  }
  return { zone: UNKNOWN, label: "Без магазина", key: `${UNKNOWN.key}:-` };
}

export function computerView(rows: Computer[], ctx: PlaceContext): ZoneView[] {
  type Bucket = { zone: { key: string; label: string }; label: string; tiles: TileView[] };
  const buckets = new Map<string, Bucket>();

  for (const row of rows) {
    const { zone, label, key } = placeComputer(row, ctx);
    const { type, id } = computerTile(row.hostname);
    const state = cashState(row);
    const tile: TileView = {
      id: row.id,
      state,
      attention: false,
      top: type,
      label: id,
      hostname: row.hostname,
      aria: `${row.hostname}, ${storeTitle(label)}, ${COMPUTER_STATE_WORD[state]}`,
    };
    const bucket = buckets.get(key) ?? { zone, label, tiles: [] };
    bucket.tiles.push(tile);
    buckets.set(key, bucket);
  }

  const zones = new Map<string, { label: string; stores: StoreView[] }>();
  for (const [key, bucket] of buckets) {
    bucket.tiles.sort((a, b) => compareText(a.hostname, b.hostname));
    const entry = zones.get(bucket.zone.key) ?? { label: bucket.zone.label, stores: [] };
    entry.stores.push({ key, label: bucket.label, title: storeTitle(bucket.label), tiles: bucket.tiles });
    zones.set(bucket.zone.key, entry);
  }
  return [...zones.entries()]
    .map(([key, z]) => makeZone(key, z.label, z.stores.sort((a, b) => compareText(a.label, b.label))))
    .sort((a, b) => (ZONE_ORDER.indexOf(a.key) === -1 ? 99 : ZONE_ORDER.indexOf(a.key)) - (ZONE_ORDER.indexOf(b.key) === -1 ? 99 : ZONE_ORDER.indexOf(b.key)));
}
