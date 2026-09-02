import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MonitorSmartphone, Rocket, Copy, X } from "lucide-react";
import {
  hostnameToRid,
  prepareRustDesk,
  rustdeskLink,
  type RemoteDevice,
} from "../client";
import { showToast } from "../lib/toastBus";

const STATE_LABEL: Record<string, string> = {
  unknown: "не проверен",
  not_installed: "не установлен",
  installing: "деплой…",
  installed: "установлен",
  configured: "готов",
  drift: "дрейф конфига",
  failed: "ошибка деплоя",
  uninstalled: "удалён",
};
const STATE_TONE: Record<string, string> = {
  configured: "bg-emerald-100 text-emerald-700",
  installed: "bg-sky-100 text-sky-700",
  installing: "bg-amber-100 text-amber-800",
  drift: "bg-amber-100 text-amber-800",
  failed: "bg-rose-100 text-rose-700",
};

type Props = {
  hostname: string;
  device?: RemoteDevice;
  canManage: boolean;
  compact?: boolean;
};

/** Connect + deploy controls for one endpoint, shown on the computer /
 *  cash-register / media-player cards. `device` comes from useRemoteDeviceMap. */
export default function RemoteAccessButtons({ hostname, device, canManage, compact }: Props) {
  const qc = useQueryClient();
  const [dlgOpen, setDlgOpen] = useState(false);
  const [rid, setRid] = useState("");
  const [pw, setPw] = useState("");

  const prepareMut = useMutation({
    mutationFn: prepareRustDesk,
    onSuccess: (r) => {
      showToast(r.job ? `Деплой RustDesk на ${hostname} поставлен в очередь` : `Задача уже в очереди`, "success");
      qc.invalidateQueries({ queryKey: ["remote-devices"] });
      setDlgOpen(false);
    },
    onError: () => showToast("Не удалось поставить деплой", "error"),
  });

  const rustId = device?.rustdesk_id ?? null;
  const state = device?.deploy_state ?? "not_installed";
  const busy = state === "installing" || prepareMut.isPending;
  const btn = `inline-flex items-center gap-1.5 rounded-lg font-medium ${
    compact ? "px-2.5 py-1.5 text-xs" : "px-3 py-2 text-sm"
  }`;

  const openDialog = () => {
    setRid(rustId ?? hostnameToRid(hostname));
    setPw("");
    setDlgOpen(true);
  };

  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5">
        {rustId && (
          <a
            href={rustdeskLink(rustId)}
            className={`${btn} bg-[var(--brand)] text-white hover:brightness-95`}
            title={`rustdesk://${rustId}`}
          >
            <MonitorSmartphone className="h-4 w-4" />
            Подключиться
          </a>
        )}
        {rustId && (
          <button
            onClick={() => {
              navigator.clipboard?.writeText(rustId).then(
                () => showToast(`ID скопирован: ${rustId}`, "success"),
                () => showToast("Не удалось скопировать", "error"),
              );
            }}
            className="rounded-lg border border-slate-200 p-2 text-slate-400 hover:bg-slate-100 hover:text-[var(--brand)]"
            title="Скопировать RustDesk ID"
          >
            <Copy className="h-3.5 w-3.5" />
          </button>
        )}
        {device && (
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
              STATE_TONE[state] ?? "bg-slate-100 text-slate-600"
            }`}
            title={device.last_error ?? undefined}
          >
            {STATE_LABEL[state] ?? state}
          </span>
        )}
        {canManage && (
          <button
            onClick={openDialog}
            disabled={busy}
            className={`${btn} app-btn-secondary disabled:opacity-50`}
            title="Установить и настроить RustDesk на этом устройстве"
          >
            <Rocket className={`h-4 w-4 ${prepareMut.isPending ? "animate-pulse" : ""}`} />
            {rustId ? "Передеплой" : "Деплой RustDesk"}
          </button>
        )}
      </div>

      {dlgOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
          <div className="app-panel w-full max-w-md space-y-4 p-5">
            <div className="flex items-start justify-between">
              <h2 className="text-base font-semibold text-slate-900">
                Деплой RustDesk · {hostname}
              </h2>
              <button onClick={() => setDlgOpen(false)} className="text-slate-400 hover:text-slate-700">
                <X className="h-5 w-5" />
              </button>
            </div>
            <p className="text-xs text-slate-500">
              Устанавливает клиент, направляет его на наш сервер, задаёт ID и постоянный пароль,
              скрывает от обычного пользователя и запрещает исходящие подключения.
            </p>
            <label className="block text-sm">
              <span className="mb-1 block text-slate-600">RustDesk ID</span>
              <input
                className="app-input w-full px-3 py-2 text-sm"
                value={rid}
                onChange={(e) => setRid(e.target.value.replace(/[^A-Za-z0-9_]/g, "_").slice(0, 32))}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-slate-600">
                Пароль {device?.has_password ? "(пусто — оставить текущий)" : "(пусто — сгенерировать)"}
              </span>
              <input
                className="app-input w-full px-3 py-2 text-sm"
                value={pw}
                onChange={(e) => setPw(e.target.value)}
                placeholder="kentdful"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDlgOpen(false)} className="app-btn-secondary px-4 py-2 text-sm">
                Отмена
              </button>
              <button
                onClick={() =>
                  prepareMut.mutate({
                    hostname,
                    rustdesk_id: rid.trim() || undefined,
                    permanent_password: pw.trim() || undefined,
                    action: rustId ? "reconfigure" : "deploy",
                  })
                }
                disabled={prepareMut.isPending}
                className="app-btn-primary px-4 py-2 text-sm disabled:opacity-50"
              >
                {rustId ? "Передеплоить" : "Задеплоить"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
