import { useRef, type ReactNode } from "react";
import { ExternalLink, KeyRound, X } from "lucide-react";
import { Link } from "react-router-dom";
import type { CashRegister, RemoteDevice } from "../../client";
import { useEscapeKey } from "../../hooks/useEscapeKey";
import { cashState, hasDrawerProblem, hasPiotProblem, isWindowsXp, storeLabel, ZONE_LABEL } from "../../lib/cashRegisters";
import { credentialsHref } from "../../lib/deviceLinks";
import { describeOfflineReason } from "../../lib/offlineReason";
import { relTime } from "../../lib/relTime";
import RemoteAccessButtons from "../RemoteAccessButtons";

const STATE_TEXT = { online: "На связи", offline: "Недоступна", unknown: "Нет данных опроса" } as const;
const STATE_CHIP = {
  online: "bg-teal-50 text-teal-800 border-teal-200 dark:bg-teal-950/40 dark:text-teal-200 dark:border-teal-900",
  offline: "bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-600",
  unknown: "bg-slate-50 text-slate-500 border-slate-200 border-dashed dark:bg-slate-900 dark:text-slate-400 dark:border-slate-700",
} as const;

function Row({ label, value, warn }: { label: string; value: ReactNode; warn?: boolean }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 text-sm">
      <dt className="shrink-0 text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className={`text-right ${warn ? "font-medium text-amber-700 dark:text-amber-300" : "text-slate-800 dark:text-slate-100"}`}>
        {value}
      </dd>
    </div>
  );
}

/** Quick look at one register with the one action the overview exists for: connect.
 *  Everything editable stays on the "Кассы" page, which this links to. */
export default function CashRegisterDrawer({
  register,
  remote,
  isSuperuser,
  onClose,
}: {
  register: CashRegister;
  remote?: RemoteDevice;
  isSuperuser: boolean;
  onClose: () => void;
}) {
  // close on a backdrop click only when the press started there too, so dragging a
  // text selection out of the panel does not throw it away
  const pressedOnBackdrop = useRef(false);
  useEscapeKey(true, onClose);

  const state = cashState(register);
  const cashHref = `/cash-registers?q=${encodeURIComponent(register.hostname)}&focus=${encodeURIComponent(register.hostname)}`;

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
        aria-label={`Касса ${register.hostname}`}
        className="flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-[var(--app-panel-border)] bg-[var(--app-panel-bg)] shadow-xl"
      >
        <header className="flex items-start justify-between gap-3 border-b border-[var(--app-panel-border)] px-5 py-4">
          <div className="min-w-0">
            <p className="truncate text-lg font-semibold text-slate-900 dark:text-slate-100">{register.hostname}</p>
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
              {storeLabel(register.store_number)}
              {register.location_zone ? ` · ${ZONE_LABEL[register.location_zone] ?? register.location_zone}` : ""}
            </p>
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

        <div className="space-y-5 px-5 py-4">
          <div>
            <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${STATE_CHIP[state]}`}>
              {STATE_TEXT[state]}
            </span>
            {state === "offline" && (
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{describeOfflineReason(register.reachability_reason)}</p>
            )}
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">Последний опрос: {relTime(register.last_polled_at)}</p>
          </div>

          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Подключение</h3>
            <RemoteAccessButtons
              hostname={register.hostname}
              device={remote}
              canManage={isSuperuser}
              unsupportedNote={isWindowsXp(register.windows_version) ? "XP касса, нельзя подключиться" : undefined}
            />
          </div>

          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Кратко</h3>
            <dl className="divide-y divide-[var(--app-panel-border)]">
              <Row label="Номер ККМ" value={register.kkm_number} />
              <Row label="Windows" value={register.windows_version} />
              <Row label="ПИОТ" value={register.piot_status} warn={hasPiotProblem(register)} />
              <Row label="Денежный ящик" value={register.cash_drawer} warn={hasDrawerProblem(register)} />
              <Row label="Терминал" value={register.terminal_status} warn />
              <Row label="Второй экран" value={register.second_screen} />
              <Row label="Комментарий" value={register.comment} />
            </dl>
          </div>
        </div>

        <footer className="mt-auto flex flex-wrap gap-2 border-t border-[var(--app-panel-border)] px-5 py-4">
          <Link to={cashHref} className="app-btn-secondary inline-flex items-center gap-1.5 px-3 py-2 text-sm">
            <ExternalLink className="h-4 w-4" />
            Все данные и правка в «Кассы»
          </Link>
          {isSuperuser && (
            <Link to={credentialsHref(register.hostname)} className="app-btn-secondary inline-flex items-center gap-1.5 px-3 py-2 text-sm">
              <KeyRound className="h-4 w-4" />
              Пароли
            </Link>
          )}
        </footer>
      </aside>
    </div>
  );
}
