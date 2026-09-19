import {
  AlertTriangle,
  CircleCheck,
  CircleDashed,
  Clock,
  Loader2,
  MonitorOff,
  RefreshCw,
  ShieldAlert,
  TimerOff,
  WifiOff,
} from "lucide-react";
import type { RemoteDevice, Readiness } from "../client";
import { relTime } from "../lib/relTime";

/** One chip per readiness value, shared by the device grid and the per-card
 *  buttons so the two surfaces never drift into different wording. */
export const READINESS_META: Record<
  Readiness,
  { label: string; toneClass: string; Icon: typeof CircleCheck }
> = {
  ready: {
    label: "Готово к подключению",
    toneClass: "bg-emerald-100 text-emerald-700",
    Icon: CircleCheck,
  },
  installed_offline: {
    label: "Развёрнуто, машина офлайн",
    toneClass: "bg-slate-100 text-slate-600",
    Icon: MonitorOff,
  },
  deploying: {
    label: "Разворачивается",
    toneClass: "bg-amber-100 text-amber-800",
    Icon: Loader2,
  },
  waiting_host: {
    label: "Ждёт включения машины",
    toneClass: "bg-sky-100 text-sky-800",
    Icon: Clock,
  },
  stalled: {
    label: "Раскатка не отработала",
    toneClass: "bg-orange-100 text-orange-800",
    Icon: TimerOff,
  },
  stale: {
    label: "Нужен передеплой",
    toneClass: "bg-amber-100 text-amber-800",
    Icon: RefreshCw,
  },
  failed: {
    label: "Ошибка развёртывания",
    toneClass: "bg-rose-100 text-rose-700",
    Icon: AlertTriangle,
  },
  unreachable: {
    label: "Машина не в сети, клиента нет",
    toneClass: "bg-slate-100 text-slate-600",
    Icon: WifiOff,
  },
  not_deployed: {
    label: "Не развёрнуто",
    toneClass: "bg-violet-100 text-violet-700",
    Icon: CircleDashed,
  },
};

/** What an operator can do about a state that is not "ready". */
const NEXT_STEP: Partial<Record<Readiness, string>> = {
  installed_offline: "клиент стоит, но машина не на связи — дождаться включения",
  waiting_host: "ничего: скрипт отработает сам, когда машину включат",
  stalled: "машина в сети, но скрипт не отчитался — проверить запуск (KSC/GPO) или запустить раскатку вручную",
  unreachable: "включить машину или проверить сеть, затем запустить раскатку",
  not_deployed: "запустить раскатку (кнопка с ракетой)",
};

/** Tooltip text behind the chip: the individual facts `readiness` was
 *  collapsed from, so "why" is one hover away instead of hidden. */
export function deviceReadinessDetail(device: RemoteDevice): string {
  const lines: string[] = [];
  if (device.online === true) lines.push(`RustDesk-консоль: на связи (${relTime(device.last_seen_at)})`);
  else if (device.online === false) lines.push(`RustDesk-консоль: не на связи (${relTime(device.last_seen_at)})`);
  else lines.push("RustDesk-консоль: ещё не регистрировался");

  if (device.host_online === true) lines.push(`Хост отвечает на пинг (${relTime(device.host_last_seen_at)})`);
  else if (device.host_online === false) lines.push(`Хост не отвечает (${relTime(device.host_last_seen_at)})`);

  const stateLabel: Record<RemoteDevice["deploy_state"], string> = {
    unknown: "раскатка не запускалась",
    pending: "ждёт запуска скрипта на машине",
    installed: "клиент установлен, конфиг ещё применяется",
    configured: "скрипт применил конфиг",
    stale: "конфиг в InfraScope изменился после раскатки — на машине ещё старый",
    failed: "скрипт сообщил об ошибке",
  };
  lines.push(`Раскатка: ${stateLabel[device.deploy_state]}`);
  if (device.deploy_state === "pending" && device.deploy_requested_at)
    lines.push(`Запрошена: ${relTime(device.deploy_requested_at)}`);
  const next = NEXT_STEP[device.readiness];
  if (next) lines.push(`Что делать: ${next}`);
  if (device.deploy_state === "failed" && device.deploy_detail) lines.push(device.deploy_detail);
  if (device.deploy_reported_at) lines.push(`Отчёт машины: ${relTime(device.deploy_reported_at)}`);

  if (device.applocker_mismatch) {
    lines.push(
      `⚠ ${device.os_caption ?? "Windows Home"}: AppLocker недоступен — запрет запуска клиента вручную не применился`,
    );
  } else if (device.os_caption) {
    lines.push(`ОС: ${device.os_caption}`);
  }

  return lines.join("\n");
}

export function ReadinessChip({
  readiness,
  title,
  compact,
}: {
  readiness: Readiness;
  title?: string;
  compact?: boolean;
}) {
  const meta = READINESS_META[readiness];
  const Icon = meta.Icon;
  return (
    <span
      title={title ?? meta.label}
      className={`inline-flex items-center gap-1 rounded-full font-medium ${meta.toneClass} ${
        compact ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs"
      }`}
    >
      <Icon className={`h-3.5 w-3.5 ${readiness === "deploying" ? "animate-spin" : ""}`} />
      {meta.label}
    </span>
  );
}

/** Small standalone warning, next to the readiness chip: block_outgoing was
 *  asked for but this device's Windows edition can't enforce it (Home has no
 *  AppLocker/AppIDSvc). Renders nothing unless the mismatch is confirmed -
 *  never warns just because the edition is still unknown. */
export function AppLockerMismatchBadge({ device, compact }: { device: RemoteDevice; compact?: boolean }) {
  if (!device.applocker_mismatch) return null;
  return (
    <span
      title={`${device.os_caption ?? "Windows Home"}: AppLocker недоступен на этой редакции — сотрудник может запустить RustDesk сам, блокировка не применилась`}
      className={`inline-flex items-center gap-1 rounded-full bg-amber-100 font-medium text-amber-800 ${
        compact ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-xs"
      }`}
    >
      <ShieldAlert className="h-3 w-3" />
      Home
    </span>
  );
}
