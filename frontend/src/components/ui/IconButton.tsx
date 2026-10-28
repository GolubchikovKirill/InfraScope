import type { ReactNode } from "react";

/** Square icon-only action for a device row; the label is its tooltip and accessible name. */
export function IconButton({
  label,
  onClick,
  children,
  disabled = false,
  danger = false,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={`app-btn-secondary inline-flex h-9 w-9 items-center justify-center disabled:opacity-40 ${danger ? "text-[var(--danger-fg)]" : ""}`}
    >
      {children}
    </button>
  );
}
