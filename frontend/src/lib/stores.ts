import { storeLabel } from "./cashRegisters";

/** Human names for stores whose code alone says little. Add a line per store. */
export const STORE_NAMES: Record<string, string> = {
  VN3: "Внуково 3",
};

/** "A2(200)" -> "A2", "А15" (Cyrillic А) -> "A15", "A14пп" -> "A14", "VN3" -> "VN3". */
export function storeCode(label: string | null | undefined): string | null {
  const raw = (label ?? "").trim();
  if (!raw) return null;
  const match = /^([A-Z]+\d+)/.exec(storeLabel(raw).toUpperCase());
  return match ? match[1] : null;
}

/** What to print on a store panel: the label, plus the name when we know one. */
export function storeTitle(label: string): string {
  const name = STORE_NAMES[storeCode(label) ?? ""];
  return name ? `${label} · ${name}` : label;
}
