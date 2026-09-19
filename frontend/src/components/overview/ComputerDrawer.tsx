import { ExternalLink, KeyRound } from "lucide-react";
import { Link } from "react-router-dom";
import type { Computer, RemoteDevice } from "../../client";
import { cashState } from "../../lib/cashRegisters";
import { credentialsHref } from "../../lib/deviceLinks";
import { describeOfflineReason } from "../../lib/offlineReason";
import { relTime } from "../../lib/relTime";
import { computerTile } from "../../lib/storeView";
import RemoteAccessButtons from "../RemoteAccessButtons";
import DrawerShell, { Row, SectionTitle, STATE_CHIP } from "./DrawerShell";

const STATE_TEXT = { online: "На связи", offline: "Недоступен", unknown: "Нет данных опроса" } as const;

/** Quick look at one computer: state, connect, the few facts we keep. Editing is on "Компьютеры". */
export default function ComputerDrawer({
  computer,
  storeTitle,
  remote,
  isSuperuser,
  onClose,
}: {
  computer: Computer;
  /** where the overview placed it (the record may have no location of its own) */
  storeTitle: string;
  remote?: RemoteDevice;
  isSuperuser: boolean;
  onClose: () => void;
}) {
  const state = cashState(computer);
  const role = computerTile(computer.hostname).type;
  const href = `/computers?q=${encodeURIComponent(computer.hostname)}&focus=${encodeURIComponent(computer.hostname)}`;

  return (
    <DrawerShell
      ariaLabel={`Компьютер ${computer.hostname}`}
      title={computer.hostname}
      subtitle={storeTitle}
      onClose={onClose}
      footer={
        <>
          <Link to={href} className="app-btn-secondary inline-flex items-center gap-1.5 px-3 py-2 text-sm">
            <ExternalLink className="h-4 w-4" />
            Все данные и правка в «Компьютеры»
          </Link>
          {isSuperuser && (
            <Link to={credentialsHref(computer.hostname)} className="app-btn-secondary inline-flex items-center gap-1.5 px-3 py-2 text-sm">
              <KeyRound className="h-4 w-4" />
              Пароли
            </Link>
          )}
        </>
      }
    >
      <div>
        <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${STATE_CHIP[state]}`}>{STATE_TEXT[state]}</span>
        {state === "offline" && <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{describeOfflineReason(computer.reachability_reason)}</p>}
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">Последний опрос: {relTime(computer.last_polled_at)}</p>
      </div>

      <div>
        <SectionTitle>Подключение</SectionTitle>
        <RemoteAccessButtons hostname={computer.hostname} device={remote} canManage={isSuperuser} />
      </div>

      <div>
        <SectionTitle>Кратко</SectionTitle>
        <dl className="divide-y divide-[var(--app-panel-border)]">
          <Row label="Роль" value={role} />
          <Row label="Магазин в записи" value={computer.location} />
          <Row label="Комментарий" value={computer.comment} />
        </dl>
      </div>
    </DrawerShell>
  );
}
