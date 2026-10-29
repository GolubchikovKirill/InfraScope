import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleHelp, CircleX, Loader2, Pencil, PlayCircle, RefreshCw, ShieldCheck, X } from "lucide-react";
import {
  checkHonestSignTarget,
  initializeHonestSignTarget,
  updateHonestSignTargetIp,
  type HonestSignCashRegisterLink,
  type HonestSignStatus,
} from "../client";
import { HONEST_SIGN_LINKS_KEY, patchHonestSignStatuses } from "../hooks/useHonestSignLinks";
import { useConfirm } from "./ConfirmDialog";
import { apiErrorMessage } from "../lib/apiError";
import { showToast } from "../lib/toastBus";

/** A status older than this many check intervals means the background check
 *  has stopped reaching the register (or has stopped running at all). */
const STALE_INTERVALS = 3;

export function isHonestSignStale(status: HonestSignStatus | null, intervalMinutes: number, autoCheck: boolean): boolean {
  if (!status || !autoCheck) return false;
  const age = Date.now() - new Date(status.checked_at).getTime();
  return age > STALE_INTERVALS * intervalMinutes * 60_000;
}

export function isHonestSignProblem(status: HonestSignStatus | null): boolean {
  return status !== null && !status.ready;
}

const RESULT_TEXT: Record<string, string> = {
  READY: "модуль готов",
  ALREADY_READY: "уже был готов",
  INITIALIZING: "инициализация выполняется",
  REQUEST_ACCEPTED: "запрос принят",
};

export default function HonestSignCashPanel({
  link,
  canManage,
  initializationConfigured,
  autoCheck,
  intervalMinutes,
}: {
  link: HonestSignCashRegisterLink;
  canManage: boolean;
  initializationConfigured: boolean;
  autoCheck: boolean;
  intervalMinutes: number;
}) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [editingIp, setEditingIp] = useState(false);
  const [ipValue, setIpValue] = useState(link.target.host);
  const { target, status } = link;
  const stale = isHonestSignStale(status, intervalMinutes, autoCheck);

  const checkMutation = useMutation({
    mutationFn: () => checkHonestSignTarget(target.host),
    onSuccess: (result) => patchHonestSignStatuses(queryClient, [result]),
    onError: (error) => showToast(apiErrorMessage(error, "Не удалось проверить Честный знак"), "error"),
  });
  const initializeMutation = useMutation({
    mutationFn: () => initializeHonestSignTarget(target.host),
    onSuccess: (result) => {
      const failed = result.result === "INIT_FAILED" || result.result === "ERROR";
      const text = `${target.host}: ${RESULT_TEXT[result.result] ?? "ошибка инициализации"}${failed && result.message ? ` — ${result.message}` : ""}`;
      showToast(text, failed ? "error" : "success");
      checkMutation.mutate();
    },
    onError: (error) => showToast(apiErrorMessage(error, "Не удалось запустить инициализацию"), "error"),
  });
  const ipMutation = useMutation({
    mutationFn: (newIp: string) => updateHonestSignTargetIp(target.original_host, newIp),
    onSuccess: async () => {
      setEditingIp(false);
      showToast("IP Local Module обновлён", "success");
      await queryClient.invalidateQueries({ queryKey: HONEST_SIGN_LINKS_KEY });
    },
    onError: (error) => showToast(apiErrorMessage(error, "Не удалось изменить IP"), "error"),
  });

  const busy = checkMutation.isPending || initializeMutation.isPending || ipMutation.isPending;
  const activate = async () => {
    const accepted = await confirm(
      `Отправить на ${target.host} запрос инициализации Local Module «Честный знак»?\nПеред запуском сервер ещё раз проверит статус: готовый модуль повторно не активируется.`,
      { confirmText: "Активировать" },
    );
    if (accepted) initializeMutation.mutate();
  };

  return (
    <div className="space-y-2 text-sm" data-testid="honest-sign-panel">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400"><ShieldCheck className="h-3.5 w-3.5" />Честный знак</span>
        <HonestSignBadge status={status} />
        {stale && <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-800" title="Фоновая проверка давно не обновляла этот статус">данные устарели</span>}
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
        {editingIp ? (
          <span className="flex items-center gap-1.5">
            <input
              value={ipValue}
              onChange={(event) => setIpValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && ipValue.trim()) ipMutation.mutate(ipValue.trim());
                if (event.key === "Escape") setEditingIp(false);
              }}
              aria-label="IP Local Module"
              autoFocus
              disabled={ipMutation.isPending}
              className="app-input w-32 px-2 py-1 font-mono text-xs"
            />
            <button type="button" title="Сохранить IP" aria-label="Сохранить IP" disabled={ipMutation.isPending || !ipValue.trim()} onClick={() => ipMutation.mutate(ipValue.trim())} className="rounded p-1 text-emerald-600 hover:bg-emerald-50 disabled:opacity-40">{ipMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}</button>
            <button type="button" title="Отмена" aria-label="Отмена" disabled={ipMutation.isPending} onClick={() => setEditingIp(false)} className="rounded p-1 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>
          </span>
        ) : (
          <span className="flex items-center gap-1">
            <span className="text-slate-400">IP: </span><span className="font-mono text-slate-700">{target.host}</span>
            {canManage && <button type="button" title="Изменить IP Local Module" aria-label="Изменить IP Local Module" onClick={() => { setIpValue(target.host); setEditingIp(true); }} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><Pencil className="h-3 w-3" /></button>}
          </span>
        )}
        <Meta label="Версия" value={status?.version || "—"} />
        <Meta label="Проверено" value={status ? new Date(status.checked_at).toLocaleString("ru-RU") : "ещё не было"} />
        {status?.state_since && <Meta label={status.ready ? "Готов с" : "Не готов с"} value={new Date(status.state_since).toLocaleString("ru-RU")} />}
      </div>
      {status?.message && <div className="rounded-lg bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">{status.message}</div>}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => checkMutation.mutate()} disabled={busy} className="app-btn-secondary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs disabled:opacity-50">
          {checkMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}Проверить Честный знак
        </button>
        {canManage && (
          <button
            type="button"
            onClick={activate}
            disabled={busy || !initializationConfigured || status?.ready === true}
            title={!initializationConfigured ? "Токен инициализации не настроен на сервере" : status?.ready ? "Модуль уже готов" : undefined}
            className="app-btn-primary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs disabled:opacity-40"
          >
            {initializeMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlayCircle className="h-3.5 w-3.5" />}Активировать
          </button>
        )}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return <span><span className="text-slate-400">{label}: </span><span className="text-slate-700">{value}</span></span>;
}

export function HonestSignBadge({ status }: { status: HonestSignStatus | null }) {
  if (!status) return <span className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">не проверено</span>;
  if (status.ready) return <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-1 text-xs font-medium text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" />готов</span>;
  if (!status.reachable) return <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-1 text-xs font-medium text-rose-700"><CircleX className="h-3.5 w-3.5" />недоступен</span>;
  if (status.status.toLocaleLowerCase("ru-RU") === "initialization") return <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-1 text-xs font-medium text-sky-700"><Loader2 className="h-3.5 w-3.5 animate-spin" />инициализация</span>;
  return <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-800"><CircleHelp className="h-3.5 w-3.5" />{status.status}</span>;
}
