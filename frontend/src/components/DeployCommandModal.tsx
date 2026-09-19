import { useQuery } from "@tanstack/react-query";
import { Copy, X } from "lucide-react";
import { getDeployCommand } from "../client";
import { showToast } from "../lib/toastBus";

type Props = {
  open: boolean;
  onClose: () => void;
};

// Runs on the admin workstation (never on this server): pushes over C$ + WMI, no reboot.
const PUSH_COMMAND = ".\rustdesk-ksc\Push-RustDesk.ps1 -ComputerName <имя-машины>";
const PUSH_COMMAND_ADMIN = PUSH_COMMAND + " -Profile admin";

/** The one line an operator pastes into a GPO startup script / schtasks. Fleet-wide and
 *  identical for every machine - the script asks InfraScope who it should be
 *  by its own hostname, so there is nothing per-device to fill in here. */
export default function DeployCommandModal({ open, onClose }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["remote-access", "deploy-command"],
    queryFn: getDeployCommand,
    enabled: open,
    staleTime: 30000,
  });

  const copy = (text: string) =>
    navigator.clipboard?.writeText(text).then(
      () => showToast("Команда скопирована", "success"),
      () => showToast("Не удалось скопировать", "error"),
    );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
      <div className="app-panel w-full max-w-xl space-y-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Команда развёртывания</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Одна и та же команда для любой машины парка — она сама узнаёт себя по
              имени компьютера и забирает у InfraScope конфиг, инсталлятор и пароль.
            </p>
          </div>
          <button onClick={onClose} className="shrink-0 text-slate-400 hover:text-slate-700">
            <X className="h-5 w-5" />
          </button>
        </div>

        {isLoading && <div className="text-sm text-slate-400">Загрузка…</div>}
        {isError && <div className="text-sm text-rose-600">Не удалось получить команду.</div>}

        {data && !data.configured && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 text-sm text-amber-900">
            Тихое развёртывание не настроено на сервере — задайте{" "}
            <code className="app-mono">RUSTDESK_DEPLOY_TOKEN</code> и{" "}
            <code className="app-mono">RUSTDESK_PUBLIC_URL</code> в{" "}
            <code className="app-mono">.env</code>. До этого раскатка возможна только push-утилитой
            с рабочей станции админа (блок ниже) или оффлайн-пакетом (кнопка «Настроить» на карточке устройства).
          </div>
        )}

        {data && data.configured && (
          <>
            <pre className="app-mono max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
              {data.command}
            </pre>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-slate-500">
                Инсталлятор: {data.installer_filename} ({data.installer_version})
              </span>
              <button
                onClick={() => copy(data.command)}
                className="app-btn-secondary inline-flex items-center gap-1.5 px-3 py-2 text-sm"
              >
                <Copy className="h-3.5 w-3.5" />
                Скопировать команду
              </button>
            </div>
            <div className="space-y-1.5 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
              <p className="font-medium text-slate-700">Куда вставить:</p>
              <ul className="list-disc space-y-0.5 pl-4">
                <li>
                  <b>GPO</b> — Computer Configuration → Scripts → Startup → PowerShell Scripts.
                </li>
                <li>
                  <b>Одна машина</b> —{" "}
                  <code className="app-mono">schtasks /S &lt;host&gt; /RU SYSTEM</code>.
                </li>
              </ul>
              <p>
                Скрипт идемпотентен: если конфиг уже применён, он ничего не переустанавливает —
                команду можно вешать на расписание. Подробности — docs/rustdesk-deployment.md.
              </p>
            </div>
          </>
        )}

        <div className="space-y-2 rounded-lg border border-sky-200 bg-sky-50 p-3 text-xs text-slate-700">
          <p className="font-medium text-slate-800">Windows 7 и раскатка без перезагрузки — с рабочей станции админа (или кнопкой «По сети»)</p>
          <p>
            Команда выше на Windows 7 с PowerShell 2.0 не сработает (нет TLS 1.2). Для «семёрок» и для любых
            машин, где перезагрузка недопустима, есть push-утилита: она сама определяет ОС, ставит MSI (Windows
            10/11) или 32-битную сборку (Windows 7), <b>ничего не перезагружает</b> и не ставит обновления.
            Запускается на вашем ПК, не на сервере. Кнопку «По сети» на карточке и над списком устройств
            обслуживает раннер, он запускает эту же утилиту (см. панель «Раскатка по сети»).
          </p>
          <pre className="app-mono whitespace-pre-wrap break-all rounded-lg bg-white p-2 text-[11px] text-slate-700">
            {PUSH_COMMAND}
          </pre>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>
              Рабочим станциям инженеров (ITD-SA) добавьте <code className="app-mono">-Profile admin</code> — без
              скрытия трея. Windows XP утилита пропускает.
            </span>
            <button
              onClick={() => copy(PUSH_COMMAND)}
              className="app-btn-secondary inline-flex items-center gap-1.5 px-3 py-2 text-sm"
            >
              <Copy className="h-3.5 w-3.5" />
              Скопировать push-команду
            </button>
          </div>
          <p>Подробности и профили — docs/rustdesk-deployment.md, раздел «Раскатка с рабочей станции админа».</p>
        </div>
      </div>
    </div>
  );
}
