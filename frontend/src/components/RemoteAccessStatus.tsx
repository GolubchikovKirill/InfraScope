import { CircleCheck, CircleDashed, Loader2, MonitorOff, AlertTriangle } from "lucide-react";
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
  failed: {
    label: "Ошибка развёртывания",
    toneClass: "bg-rose-100 text-rose-700",
    Icon: AlertTriangle,
  },
  not_deployed: {
    label: "Не развёрнуто",
    toneClass: "bg-slate-100 text-slate-400",
    Icon: CircleDashed,
  },
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
    failed: "скрипт сообщил об ошибке",
  };
  lines.push(`Раскатка: ${stateLabel[device.deploy_state]}`);
  if (device.deploy_state === "failed" && device.deploy_detail) lines.push(device.deploy_detail);
  if (device.deploy_reported_at) lines.push(`Отчёт машины: ${relTime(device.deploy_reported_at)}`);

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
