import { useEffect, useRef } from "react";
import { normalizeHostKey, rowDomId } from "../lib/deviceLinks";

export interface FocusableRow {
  /** Identity used to build the row's DOM id - pass the same value used to
   *  render `id={rowDomId(identity)}` on that row. */
  id: string;
  /** Every value a `?focus=` link might arrive with (hostname, IP, name, …). */
  keys: Array<string | null | undefined>;
}

/** Scrolls to and briefly highlights the row named by `focusKey` (typically
 *  the URL's `?focus=` param) once it appears among `rows`. Matches loosely
 *  (see normalizeHostKey) since the link and the row may spell a hostname
 *  differently. Fires once per focusKey value - a later data refresh with
 *  the same rows does not re-trigger the flash. */
export function useRowFocus(focusKey: string, rows: FocusableRow[]): void {
  const handledRef = useRef<string | null>(null);

  useEffect(() => {
    if (!focusKey) {
      handledRef.current = null;
      return;
    }
    if (handledRef.current === focusKey) return;
    const target = normalizeHostKey(focusKey);
    if (!target) return;

    const match = rows.find((row) => row.keys.some((key) => key && normalizeHostKey(key) === target));
    if (!match) return; // rows may still be loading - retry once they arrive

    const el = document.getElementById(rowDomId(match.id));
    if (!el) return;

    handledRef.current = focusKey;
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView?.({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
    el.classList.add("row-flash");
    const timer = window.setTimeout(() => el.classList.remove("row-flash"), 1600);
    return () => window.clearTimeout(timer);
  }, [focusKey, rows]);
}
