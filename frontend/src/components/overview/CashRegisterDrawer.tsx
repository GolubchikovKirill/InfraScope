import { ExternalLink, KeyRound } from "lucide-react";
import { Link } from "react-router-dom";
import type { CashRegister, RemoteDevice } from "../../client";
import { cashState, hasDrawerProblem, hasPiotProblem, isWindowsXp, storeLabel, ZONE_LABEL } from "../../lib/cashRegisters";
import { credentialsHref } from "../../lib/deviceLinks";
import { describeOfflineReason } from "../../lib/offlineReason";
import { relTime } from "../../lib/relTime";
import { storeTitle } from "../../lib/stores";
import RemoteAccessButtons from "../RemoteAccessButtons";
import DrawerShell, { Row, SectionTitle, STATE_CHIP } from "./DrawerShell";

const STATE_TEXT = { online: "На связи", offline: "Недоступна", unknown: "Нет данных опроса" } as const;

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
  const state = cashState(register);
  const cashHref = `/cash-registers?q=${encodeURIComponent(register.hostname)}&focus=${encodeURIComponent(register.hostname)}`;

  return (
    <DrawerShell
      ariaLabel={`Касса ${register.hostname}`}
      title={register.hostname}
      subtitle={`${storeTitle(storeLabel(register.store_number))}${register.location_zone ? ` · ${ZONE_LABEL[register.location_zone] ?? register.location_zone}` : ""}`}
      onClose={onClose}
      footer={
        <>
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
        </>
      }
    >
      <div>
        <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${STATE_CHIP[state]}`}>{STATE_TEXT[state]}</span>
        {state === "offline" && <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{describeOfflineReason(register.reachability_reason)}</p>}
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">Последний опрос: {relTime(register.last_polled_at)}</p>
      </div>

      <div>
        <SectionTitle>Подключение</SectionTitle>
        <RemoteAccessButtons
          hostname={register.hostname}
          device={remote}
          canManage={isSuperuser}
          unsupportedNote={isWindowsXp(register.windows_version) ? "XP касса, нельзя подключиться" : undefined}
        />
      </div>

      <div>
        <SectionTitle>Кратко</SectionTitle>
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
    </DrawerShell>
  );
}
