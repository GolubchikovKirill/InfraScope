export type ToastType = "success" | "error" | "info";

export interface ToastMessage {
  id: number;
  type: ToastType;
  text: string;
}

type Listener = (toast: ToastMessage) => void;

let idCounter = 0;
const listeners = new Set<Listener>();

export function showToast(text: string, type: ToastType = "info"): void {
  const toast: ToastMessage = { id: ++idCounter, type, text };
  listeners.forEach((listener) => listener(toast));
}

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
