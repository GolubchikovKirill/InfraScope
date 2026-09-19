import type { CashRegister } from "../client";

export type CashState = "online" | "offline" | "unknown";

export const ZONE_LABEL: Record<string, string> = {
  DF: "Duty Free",
  DP: "Duty Paid",
};

/** PIOT is filled in and is not "Обновлен". */
export function hasPiotProblem(item: Pick<CashRegister, "piot_status">): boolean {
  const piot = (item.piot_status || "").trim().toLocaleUpperCase("ru-RU");
  return Boolean(piot) && (piot.includes("НЕ ОБНОВЛЕН") || !piot.includes("ОБНОВЛЕН"));
}

/** The cash drawer field is filled in and is not "да". */
export function hasDrawerProblem(item: Pick<CashRegister, "cash_drawer">): boolean {
  const drawer = (item.cash_drawer || "").trim().toLocaleLowerCase("ru-RU");
  return Boolean(drawer) && drawer !== "да";
}

/** True when something around the register needs a look (whether or not it answers):
 *  a terminal status is set, PIOT is not updated, or the cash drawer is not "да". */
export function isAttention(item: CashRegister): boolean {
  return Boolean(item.terminal_status) || hasPiotProblem(item) || hasDrawerProblem(item);
}

// windows_version holds both Latin "XP" and Cyrillic "ХР" (the inventory spreadsheet mixes them)
export const isWindowsXp = (value: string | null | undefined): boolean => /^(xp|хр)$/i.test((value ?? "").trim());

export function cashState(item: Pick<CashRegister, "is_online">): CashState {
  if (item.is_online === true) return "online";
  if (item.is_online === false) return "offline";
  return "unknown";
}

// Cyrillic letters that look like Latin ones. The store column was typed by hand and
// the same store shows up as "A5(203)" and "А5 (203)" (first letter Cyrillic).
const LOOKALIKES: Record<string, string> = {
  А: "A", В: "B", Е: "E", К: "K", М: "M", Н: "H", О: "O", Р: "P", С: "C", Т: "T", Х: "X",
};

/** Display label of a store: look-alike letters folded to Latin, no space before "(". */
export function storeLabel(storeNumber: string | null | undefined): string {
  const raw = (storeNumber ?? "").trim();
  if (!raw) return "Без магазина";
  return raw
    .replace(/[А-ЯЁ]/g, (ch) => LOOKALIKES[ch] ?? ch)
    .replace(/\s+\(/g, "(")
    .replace(/\s+/g, " ");
}

/** Short text for a tile: the number at the end of the hostname (VNA-KKM-1506 -> 1506). */
export function tileLabel(hostname: string | null | undefined): string {
  const host = (hostname ?? "").trim();
  const digits = host.match(/(\d+)$/);
  if (digits) return digits[1];
  return host.slice(-5) || "—";
}

export type StoreGroup = { key: string; label: string; rows: CashRegister[] };

export type ZoneGroup = {
  zone: string;
  label: string;
  stores: StoreGroup[];
  total: number;
  online: number;
  offline: number;
  unknown: number;
  attention: number;
};

const compareText = (a: string, b: string) => a.localeCompare(b, "ru", { numeric: true, sensitivity: "base" });
const ZONE_ORDER = ["DF", "DP"];

/** Zone -> store -> registers, in the order an operator scans a shop list. */
export function groupByZoneAndStore(rows: CashRegister[]): ZoneGroup[] {
  const zones = new Map<string, Map<string, StoreGroup>>();
  for (const row of rows) {
    const zone = row.location_zone ?? "none";
    const label = storeLabel(row.store_number);
    const stores = zones.get(zone) ?? new Map<string, StoreGroup>();
    const group = stores.get(label) ?? { key: `${zone}:${label}`, label, rows: [] };
    group.rows.push(row);
    stores.set(label, group);
    zones.set(zone, stores);
  }

  const result: ZoneGroup[] = [];
  for (const [zone, stores] of zones) {
    const groups = [...stores.values()].sort((a, b) => compareText(a.label, b.label));
    for (const group of groups) {
      group.rows.sort(
        (a, b) =>
          (a.source_order ?? Number.MAX_SAFE_INTEGER) - (b.source_order ?? Number.MAX_SAFE_INTEGER) ||
          compareText(a.hostname, b.hostname),
      );
    }
    const all = groups.flatMap((g) => g.rows);
    result.push({
      zone,
      label: ZONE_LABEL[zone] ?? "Без зоны",
      stores: groups,
      total: all.length,
      online: all.filter((r) => cashState(r) === "online").length,
      offline: all.filter((r) => cashState(r) === "offline").length,
      unknown: all.filter((r) => cashState(r) === "unknown").length,
      attention: all.filter(isAttention).length,
    });
  }
  return result.sort((a, b) => {
    const ia = ZONE_ORDER.indexOf(a.zone);
    const ib = ZONE_ORDER.indexOf(b.zone);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
}
