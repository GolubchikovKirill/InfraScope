import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { useEscapeKey } from "../hooks/useEscapeKey";

interface ConfirmOptions {
  danger?: boolean;
  confirmText?: string;
  cancelText?: string;
}

interface ConfirmState extends ConfirmOptions {
  message: string;
  resolve: (value: boolean) => void;
}

type ConfirmFn = (message: string, options?: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ConfirmState | null>(null);

  const confirm = useCallback<ConfirmFn>((message, options) => {
    return new Promise<boolean>((resolve) => {
      setState({ message, resolve, ...options });
    });
  }, []);

  const settle = (result: boolean) => {
    state?.resolve(result);
    setState(null);
  };

  useEscapeKey(state !== null, () => settle(false));

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {state && (
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 p-4"
          onClick={() => settle(false)}
        >
          <div
            className="app-panel w-full max-w-sm rounded-xl border p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              {state.danger && <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />}
              <p className="whitespace-pre-line text-sm text-gray-800">{state.message}</p>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => settle(false)}
                className="rounded-lg border px-3 py-1.5 text-sm text-gray-600 transition hover:bg-gray-50"
              >
                {state.cancelText || "Отмена"}
              </button>
              <button
                onClick={() => settle(true)}
                autoFocus
                className={`rounded-lg px-3 py-1.5 text-sm font-medium text-white transition ${
                  state.danger ? "bg-red-600 hover:bg-red-700" : "bg-rose-600 hover:bg-rose-700"
                }`}
              >
                {state.confirmText || "Подтвердить"}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within ConfirmProvider");
  return ctx;
}
