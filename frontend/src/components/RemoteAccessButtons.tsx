import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MonitorSmartphone, Settings2, Copy, X, FileCog, CircleCheck, CircleX, CircleDashed } from "lucide-react";
import {
  ensureRustDeskDevice,
  getDevicePackage,
  hostnameToRid,
  rustdeskLink,
  type RemoteDevice,
} from "../client";
import { showToast } from "../lib/toastBus";

type Props = {
  hostname: string;
  device?: RemoteDevice;
  canManage: boolean;
  compact?: boolean;
};

/** Connect + config controls for one endpoint, shown on the computer /
 *  cash-register / media-player cards. `device` comes from useRemoteDeviceMap.
 *  The client is rolled out via KSC - these buttons only connect and record
 *  the desired config. */
export default function RemoteAccessButtons({ hostname, device, canManage, compact }: Props) {
  const qc = useQueryClient();
  const [dlgOpen, setDlgOpen] = useState(false);
  const [pkgOpen, setPkgOpen] = useState(false);
  const [rid, setRid] = useState("");
  const [pw, setPw] = useState("");

  const ensureMut = useMutation({
    mutationFn: ensureRustDeskDevice,
    onSuccess: () => {
      showToast(`Конфиг RustDesk для ${hostname} сохранён`, "success");
      qc.invalidateQueries({ queryKey: ["remote-devices"] });
      setDlgOpen(false);
    },
    onError: () => showToast("Не удалось сохранить конфиг", "error"),
  });

  const pkg = useQuery({
    queryKey: ["remote-package", device?.id],
    queryFn: () => getDevicePackage(device!.id),
    enabled: pkgOpen && !!device?.id,
    retry: false,
  });

  const rustId = device?.rustdesk_id ?? null;
  const online = device?.online ?? null;
  const btn = `inline-flex items-center gap-1.5 rounded-lg font-medium ${
    compact ? "px-2.5 py-1.5 text-xs" : "px-3 py-2 text-sm"
  }`;

  const openDialog = () => {
    setRid(rustId ?? hostnameToRid(hostname));
    setPw("");
    setDlgOpen(true);
  };

  const copy = (text: string, label: string) =>
    navigator.clipboard?.writeText(text).then(
      () => showToast(`${label} скопирован`, "success"),
      () => showToast("Не удалось скопировать", "error"),
    );

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
            onClick={() => copy(rustId, "RustDesk ID")}
            className="rounded-lg border border-slate-200 p-2 text-slate-400 hover:bg-slate-100 hover:text-[var(--brand)]"
            title="Скопировать RustDesk ID"
          >
            <Copy className="h-3.5 w-3.5" />
          </button>
        )}
        {device && (
          <span
            className="inline-flex items-center gap-1 text-xs text-slate-500"
            title="RustDesk-консоль: клиент на связи"
          >
            {online === true ? (
              <CircleCheck className="h-3.5 w-3.5 text-emerald-500" />
            ) : online === false ? (
              <CircleX className="h-3.5 w-3.5 text-slate-400" />
            ) : (
              <CircleDashed className="h-3.5 w-3.5 text-slate-300" />
            )}
            RustDesk
            {device.in_address_book && <span className="text-emerald-600"> · в книге</span>}
          </span>
        )}
        {canManage && (
          <>
            <button onClick={openDialog} className={`${btn} app-btn-secondary`} title="Задать RustDesk ID и пароль">
              <Settings2 className="h-4 w-4" />
              Настроить
            </button>
            {device && (
              <button
                onClick={() => setPkgOpen(true)}
                className={`${btn} app-btn-secondary`}
                title="Показать конфиг для пакета KSC"
              >
                <FileCog className="h-4 w-4" />
                Пакет KSC
              </button>
            )}
          </>
        )}
      </div>

      {dlgOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
          <div className="app-panel w-full max-w-md space-y-4 p-5">
            <div className="flex items-start justify-between">
              <h2 className="text-base font-semibold text-slate-900">RustDesk · {hostname}</h2>
              <button onClick={() => setDlgOpen(false)} className="text-slate-400 hover:text-slate-700">
                <X className="h-5 w-5" />
              </button>
            </div>
            <p className="text-xs text-slate-500">
              Сохраняет желаемый ID и пароль для этой машины. Применяется на устройство при
              раскатке пакета через KSC — здесь ничего не устанавливается.
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
                  ensureMut.mutate({
                    hostname,
                    rustdesk_id: rid.trim() || undefined,
                    permanent_password: pw.trim() || undefined,
                  })
                }
                disabled={ensureMut.isPending}
                className="app-btn-primary px-4 py-2 text-sm disabled:opacity-50"
              >
                Сохранить
              </button>
            </div>
          </div>
        </div>
      )}

      {pkgOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
          <div className="app-panel w-full max-w-lg space-y-3 p-5">
            <div className="flex items-start justify-between">
              <h2 className="text-base font-semibold text-slate-900">rustdesk-ksc.json · {hostname}</h2>
              <button onClick={() => setPkgOpen(false)} className="text-slate-400 hover:text-slate-700">
                <X className="h-5 w-5" />
              </button>
            </div>
            {pkg.isLoading && <div className="text-sm text-slate-400">Загрузка…</div>}
            {pkg.isError && (
              <div className="text-sm text-rose-600">Не удалось получить конфиг.</div>
            )}
            {pkg.data && (
              <>
                <pre className="app-mono max-h-72 overflow-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
                  {JSON.stringify(
                    {
                      id_server: pkg.data.id_server,
                      relay_server: pkg.data.relay_server,
                      api_server: pkg.data.api_server,
                      key: pkg.data.key,
                      rustdesk_id: pkg.data.rustdesk_id,
                      permanent_password: pkg.data.permanent_password,
                      installer_version: pkg.data.installer_version,
                      hidden: pkg.data.hidden,
                      block_outgoing: pkg.data.block_outgoing,
                      unattended: pkg.data.unattended,
                    },
                    null,
                    2,
                  )}
                </pre>
                <div className="flex justify-end">
                  <button
                    onClick={() => copy(JSON.stringify(pkg.data, null, 2), "Конфиг")}
                    className="app-btn-secondary inline-flex items-center gap-1.5 px-3 py-2 text-sm"
                  >
                    <Copy className="h-3.5 w-3.5" />
                    Скопировать
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
