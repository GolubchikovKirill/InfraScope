// Small pieces the credential vault's dialogs share.
import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { CREDENTIAL_CATEGORIES, type CredentialCategory } from "../../client";
import { showToast } from "../../lib/toastBus";

export const CATEGORY_LABEL: Record<CredentialCategory, string> = Object.fromEntries(
  CREDENTIAL_CATEGORIES.map((c) => [c.value, c.label]),
) as Record<CredentialCategory, string>;

export function categoryTone(category: CredentialCategory): string {
  const map: Partial<Record<CredentialCategory, string>> = {
    switch: "bg-sky-100 text-sky-700",
    printer: "bg-slate-100 text-slate-600",
    cash_register: "bg-violet-100 text-violet-700",
    computer: "bg-indigo-100 text-indigo-700",
    media_player: "bg-amber-100 text-amber-800",
    camera: "bg-teal-100 text-teal-700",
    server: "bg-rose-100 text-rose-700",
    service: "bg-emerald-100 text-emerald-700",
    website: "bg-blue-100 text-blue-700",
    email: "bg-orange-100 text-orange-700",
  };
  return map[category] ?? "bg-slate-100 text-slate-600";
}

export async function copyText(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(`${label} скопирован`, "success");
  } catch {
    showToast("Не удалось скопировать", "error");
  }
}

export function Toggle({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className={`inline-flex items-center gap-2 text-sm ${disabled ? "opacity-50" : "cursor-pointer"}`}>
      <input
        type="checkbox"
        className="h-4 w-4 accent-[var(--brand)]"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="text-slate-600">{label}</span>
    </label>
  );
}

export function Field({ label, className = "", children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={`block text-sm ${className}`}>
      <span className="mb-1 block text-slate-600">{label}</span>
      {children}
    </label>
  );
}

export function Modal({
  title,
  onClose,
  wide,
  children,
}: {
  title: string;
  onClose: () => void;
  wide?: boolean;
  children: React.ReactNode;
}) {
  const pressedOnBackdrop = useRef(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    // Close on a click of the backdrop only when the press started there too. Dragging
    // a text selection out of an input and releasing over the backdrop also fires a
    // "click" on it, which used to throw away a half-filled form.
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onMouseDown={(e) => {
        pressedOnBackdrop.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && pressedOnBackdrop.current) onClose();
        pressedOnBackdrop.current = false;
      }}
    >
      <div
        role="dialog"
        aria-label={title}
        className={`app-panel w-full ${wide ? "max-w-2xl" : "max-w-md"} max-h-[90vh] overflow-y-auto p-5`}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-900">{title}</h3>
          <button className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
