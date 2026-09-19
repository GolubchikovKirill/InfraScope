import type { CashRegister, RemoteDevice } from "../client";
import { buildStoreIndex, placeComputer, type StoreIndex } from "./storeView";
import { storeTitle } from "./stores";

/** A screen is a TV box: the store display machines are named VNA-TV-<store><n> (VNA-TV-401,
 *  vna-tv-2702). The role token comes off the hostname, so nothing has to be tagged by hand. */
export function isScreen(device: Pick<RemoteDevice, "type_tag">): boolean {
  return (device.type_tag ?? "").toUpperCase() === "TV";
}

/** online: the RustDesk client is connected. reachable: the machine answers a ping but the client
 *  is not connected (connect will not work yet). offline: neither. unknown: never polled. */
export type ScreenState = "online" | "reachable" | "offline" | "unknown";

export function screenState(device: Pick<RemoteDevice, "online" | "host_online">): ScreenState {
  if (device.online === true) return "online";
  if (device.host_online === true) return "reachable";
  if (device.online === false || device.host_online === false) return "offline";
  return "unknown";
}

/** "Active" is what the screens tab shows by default: the client is connected, or at least the
 *  machine is up. */
export const isActiveScreen = (device: Pick<RemoteDevice, "online" | "host_online">): boolean => {
  const state = screenState(device);
  return state === "online" || state === "reachable";
};

export type ScreenStore = { key: string; label: string; title: string; screens: RemoteDevice[] };
export type ScreenZone = { key: string; label: string; stores: ScreenStore[]; total: number; active: number };

const compareText = (a: string, b: string) => a.localeCompare(b, "ru", { numeric: true, sensitivity: "base" });
const ZONE_ORDER = ["DF", "DP", "stores", "office", "unknown"];

/** Screens by zone and store, using the same placement as the overview map: the record's own
 *  location, else the number in the hostname (VNA-TV-401 -> A4), matched to the label the cash
 *  registers already give that store. */
export function groupScreens(screens: RemoteDevice[], cashRegisters: CashRegister[], storeIndex?: StoreIndex): ScreenZone[] {
  const index = storeIndex ?? buildStoreIndex(cashRegisters);
  const zones = new Map<string, { label: string; stores: Map<string, ScreenStore> }>();

  for (const screen of screens) {
    const { zone, label, key } = placeComputer({ hostname: screen.hostname, location: screen.location }, { storeIndex: index, remoteLocation: () => null });
    const entry = zones.get(zone.key) ?? { label: zone.label, stores: new Map<string, ScreenStore>() };
    const store = entry.stores.get(key) ?? { key, label, title: storeTitle(label), screens: [] };
    store.screens.push(screen);
    entry.stores.set(key, store);
    zones.set(zone.key, entry);
  }

  return [...zones.entries()]
    .map(([key, z]) => {
      const stores = [...z.stores.values()].sort((a, b) => compareText(a.label, b.label));
      for (const store of stores) store.screens.sort((a, b) => compareText(a.hostname, b.hostname));
      const all = stores.flatMap((s) => s.screens);
      return { key, label: z.label, stores, total: all.length, active: all.filter(isActiveScreen).length };
    })
    .sort((a, b) => (ZONE_ORDER.indexOf(a.key) === -1 ? 99 : ZONE_ORDER.indexOf(a.key)) - (ZONE_ORDER.indexOf(b.key) === -1 ? 99 : ZONE_ORDER.indexOf(b.key)));
}

/** Keep what matches a search text: a screen by its hostname, or every screen of a store whose name
 *  or code matches ("внуково", "A4"). Empty stores and zones drop out and the counts are redone. */
export function filterScreenZones(zones: ScreenZone[], search: string): ScreenZone[] {
  const needle = search.trim().toLowerCase();
  if (!needle) return zones;
  const result: ScreenZone[] = [];
  for (const zone of zones) {
    const stores = zone.stores
      .map((store) =>
        store.title.toLowerCase().includes(needle)
          ? store
          : { ...store, screens: store.screens.filter((s) => s.hostname.toLowerCase().includes(needle)) },
      )
      .filter((store) => store.screens.length > 0);
    if (!stores.length) continue;
    const all = stores.flatMap((st) => st.screens);
    result.push({ ...zone, stores, total: all.length, active: all.filter(isActiveScreen).length });
  }
  return result;
}
