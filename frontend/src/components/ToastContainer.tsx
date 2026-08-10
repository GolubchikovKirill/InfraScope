import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";
import { subscribeToasts, type ToastMessage } from "../lib/toastBus";

const AUTO_DISMISS_MS = 5000;

const STYLES: Record<ToastMessage["type"], string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  error: "border-[var(--danger-border)] bg-[var(--danger-bg)] text-[var(--danger-fg)]",
  info: "border-gray-200 bg-white text-gray-800",
};

function ToastIcon({ type }: { type: ToastMessage["type"] }) {
  if (type === "success") return <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />;
  if (type === "error") return <XCircle className="h-5 w-5 shrink-0 text-[var(--danger-fg)]" />;
  return <Info className="h-5 w-5 shrink-0 text-gray-400" />;
}

export default function ToastContainer() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const remove = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    return subscribeToasts((toast) => {
      setToasts((prev) => [...prev, toast]);
      window.setTimeout(() => remove(toast.id), AUTO_DISMISS_MS);
    });
  }, [remove]);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className={`toast-in app-panel flex items-start gap-2.5 rounded-xl border p-3 shadow-lg ${STYLES[toast.type]}`}
        >
          <ToastIcon type={toast.type} />
          <div className="flex-1 text-sm">{toast.text}</div>
          <button
            onClick={() => remove(toast.id)}
            className="shrink-0 text-gray-400 transition hover:text-gray-600"
            aria-label="Закрыть уведомление"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
