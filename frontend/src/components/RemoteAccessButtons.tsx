import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MonitorSmartphone, Settings2, Copy, X, FileCog, Rocket, RotateCcw } from "lucide-react";
import {
  ensureRustDeskDevice,
  getDevicePackage,
  hostnameToRid,
  requestDeploy,
  rustdeskLink,
  setDeviceProfile,
  type DeployProfile,
  type RemoteDevice,
} from "../client";
import { showToast } from "../lib/toastBus";
import { AppLockerMismatchBadge, ReadinessChip, deviceReadinessDetail } from "./RemoteAccessStatus";
import DeployCommandModal from "./DeployCommandModal";

type Props = {
  hostname: string;
  device?: RemoteDevice;
  canManage: boolean;
  compact?: boolean;
  /** Set for machines RustDesk cannot run on (Windows XP): replaces every remote-access control with this note. */
  unsupportedNote?: string;
};

/** Connect + config controls for one endpoint, shown on the computer /
 *  cash-register / media-player cards. `device` comes from useRemoteDeviceMap.
 *  InfraScope rolls the client out itself now (pull model, see
 *  docs/rustdesk-v2-plan.md) - "Развернуть" only marks the machine as awaiting
 *  the bootstrap and shows the one-line command; nothing runs from here. */
export default function RemoteAccessButtons({ hostname, device, canManage, compact, unsupportedNote }: Props) {
  const qc = useQueryClient();
  const [dlgOpen, setDlgOpen] = useState(false);
  const [pkgOpen, setPkgOpen] = useState(false);
  const [deployModalOpen, setDeployModalOpen] = useState(false);
  const [rid, setRid] = useState("");
  const [pw, setPw] = useState("");

  const ensureMut = useMutation({
    // wrapped (not point-free): a bare `mutationFn: ensureRustDeskDevice` would
    // still work at runtime - TanStack Query's extra context arg is silently
    // ignored - but it is an implicit dependency on that being harmless
    mutationFn: (payload: Parameters<typeof ensureRustDeskDevice>[0]) => ensureRustDeskDevice(payload),
    onSuccess: () => {
      showToast(`Конфиг RustDesk для ${hostname} сохранён`, "success");
      qc.invalidateQueries({ queryKey: ["remote-devices"] });
      setDlgOpen(false);
    },
    onError: () => showToast("Не удалось сохранить конфиг", "error"),
  });

  const deployMut = useMutation({
    mutationFn: (id: string) => requestDeploy(id),
    onSuccess: () => {
      showToast(`${hostname}: ждёт запуска скрипта на машине`, "success");
      qc.invalidateQueries({ queryKey: ["remote-devices"] });
      setDeployModalOpen(true);
    },
    onError: () => showToast("Не удалось запросить развёртывание", "error"),
  });

  const profileMut = useMutation({
    mutationFn: ({ id, profile }: { id: string; profile: DeployProfile }) => setDeviceProfile(id, profile),
    onSuccess: (dev) => {
      showToast(
        dev.deploy_profile === "admin"
          ? `${hostname}: профиль «Админ» — полный доступ, без ограничений`
          : `${hostname}: профиль «Клиент» — заблокировано для пользователя`,
        "success",
      );
      qc.invalidateQueries({ queryKey: ["remote-devices"] });
    },
    onError: () => showToast("Не удалось сменить профиль", "error"),
  });

  const pkg = useQuery({
    queryKey: ["remote-package", device?.id],
    queryFn: () => getDevicePackage(device!.id),
    enabled: pkgOpen && !!device?.id,
    retry: false,
  });

  const rustId = device?.rustdesk_id ?? null;
  // an entry that was removed from management: the ID still connects, but nothing is pushed to the
  // address book and there is no rollout state to show until it is taken back
  const unmanaged = device?.managed === false;
  // the button reapplies the entire desired config on every run, not just
  // what changed - "Передеплоить" reads better once it has ever succeeded
  const redeploy =
    device?.readiness === "ready" || device?.readiness === "installed_offline" || device?.readiness === "stale";
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

  if (unsupportedNote) {
    return (
      <span
        className={`inline-flex items-center rounded-lg bg-amber-100 font-medium text-amber-800 ${
          compact ? "px-2.5 py-1.5 text-xs" : "px-3 py-2 text-sm"
        }`}
      >
        {unsupportedNote}
      </span>
    );
  }

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
        {device && unmanaged && (
          <span
            title="Запись снята с управления: подключение по ID работает, но пароль в общую книгу не подставляется. «Вернуть в управление» включит её обратно."
            className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600"
          >
            Не в управлении
          </span>
        )}
        {device && !unmanaged && (
          <>
            <ReadinessChip readiness={device.readiness} title={deviceReadinessDetail(device)} compact />
            <AppLockerMismatchBadge device={device} compact />
          </>
        )}
        {canManage && (
          <>
            <button onClick={openDialog} className={`${btn} app-btn-secondary`} title="Задать RustDesk ID и пароль">
              <Settings2 className="h-4 w-4" />
              Настроить
            </button>
            {device && unmanaged && (
              <button
                onClick={() => ensureMut.mutate({ hostname })}
                disabled={ensureMut.isPending}
                className={`${btn} app-btn-secondary disabled:opacity-50`}
                title="Снова вести эту машину в удалённом доступе (пароль вернётся в общую книгу в течение пары минут)"
              >
                <RotateCcw className="h-4 w-4" />
                Вернуть в управление
              </button>
            )}
            {device && !unmanaged && (
              <button
                onClick={() => deployMut.mutate(device.id)}
                disabled={deployMut.isPending}
                className={`${btn} app-btn-secondary disabled:opacity-50`}
                title={
                  redeploy
                    ? "Передеплоить: заново применить текущие ID, пароль и настройки скрытности/блокировки"
                    : "Тихо развернуть через InfraScope"
                }
              >
                <Rocket className="h-4 w-4" />
                {redeploy ? "Передеплоить" : "Развернуть"}
              </button>
            )}
            {device && !unmanaged && (
              <button
                onClick={() => setPkgOpen(true)}
                className="rounded-lg border border-slate-200 p-2 text-slate-400 hover:bg-slate-100 hover:text-[var(--brand)]"
                title="Оффлайн-пакет KSC (для машин без сети до InfraScope)"
              >
                <FileCog className="h-3.5 w-3.5" />
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
              следующем прогоне раскатки — здесь ничего не устанавливается.
            </p>
            {device && (
              <label className="block text-sm">
                <span className="mb-1 block text-slate-600">Профиль</span>
                <select
                  className="app-input w-full px-3 py-2 text-sm"
                  value={device.deploy_profile}
                  disabled={profileMut.isPending}
                  onChange={(e) =>
                    profileMut.mutate({ id: device.id, profile: e.target.value as DeployProfile })
                  }
                >
                  <option value="client">Клиент — скрыт, самому не запустить</option>
                  <option value="admin">Админ — полный доступ, как обычный RustDesk</option>
                </select>
              </label>
            )}
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
            <p className="text-xs text-slate-500">
              Только для машин без сети до InfraScope — конфиг зашивается в пакет KSC, InfraScope не
              узнает о результате установки. Если сеть есть, используйте «Развернуть».
            </p>
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

      <DeployCommandModal open={deployModalOpen} onClose={() => setDeployModalOpen(false)} />
    </>
  );
}
