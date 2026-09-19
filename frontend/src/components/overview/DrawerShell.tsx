import { useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { useEscapeKey } from "../../hooks/useEscapeKey";
import type { CashState } from "../../lib/cashRegisters";

export const STATE_CHIP: Record<CashState, string> = {
  online: "bg-teal-50 text-teal-800 border-teal-200 dark:bg-teal-950/40 dark:text-teal-200 dark:border-teal-900",
  offline: "bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-600",
  unknown: "bg-slate-50 text-slate-500 border-slate-200 border-dashed dark:bg-slate-900 dark:text-slate-400 dark:border-slate-700",
};

export function Row({ label, value, warn }: { label: string; value: ReactNode; warn?: boolean }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 text-sm">
      <dt className="shrink-0 text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className={`text-right ${warn ? "font-medium text-amber-700 dark:text-amber-300" : "text-slate-800 dark:text-slate-100"}`}>{value}</dd>
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{children}</h3>;
}

/** The side panel every quick look shares: backdrop, header, scrollable body, footer. */
export default function DrawerShell({
  ariaLabel,
  title,
  subtitle,
  footer,
  onClose,
  children,
}: {
  ariaLabel: string;
  title: string;
  subtitle: string;
  footer: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  // close on a backdrop click only when the press started there too, so dragging a
  // text selection out of the panel does not throw it away
  const pressedOnBackdrop = useRef(false);
  useEscapeKey(true, onClose);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-900/30 backdrop-blur-[1px]"
      onMouseDown={(e) => {
        pressedOnBackdrop.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && pressedOnBackdrop.current) onClose();
        pressedOnBackdrop.current = false;
      }}
    >
      <aside
        role="dialog"
        aria-label={ariaLabel}
        className="flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-[var(--app-panel-border)] bg-[var(--app-panel-bg)] shadow-xl"
      >
        <header className="flex items-start justify-between gap-3 border-b border-[var(--app-panel-border)] px-5 py-4">
          <div className="min-w-0">
            <p className="truncate text-lg font-semibold text-slate-900 dark:text-slate-100">{title}</p>
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800"
          >
            <X className="h-5 w-5" />
          </button>
        </header>
        <div className="space-y-5 px-5 py-4">{children}</div>
        <footer className="mt-auto flex flex-wrap gap-2 border-t border-[var(--app-panel-border)] px-5 py-4">{footer}</footer>
      </aside>
    </div>
  );
}
