import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, Clock, Loader2, MinusCircle, Network, X } from "lucide-react";
import { cancelPushJob, getPushJobs, type PushJob, type PushJobState } from "../client";
import { relTime } from "../lib/relTime";
import { showToast } from "../lib/toastBus";

const STATE: Record<PushJobState, { label: string; tone: string; Icon: typeof Clock }> = {
  queued: { label: "в очереди", tone: "bg-sky-100 text-sky-800", Icon: Clock },
  running: { label: "выполняется", tone: "bg-amber-100 text-amber-800", Icon: Loader2 },
  succeeded: { label: "готово", tone: "bg-emerald-100 text-emerald-700", Icon: CircleCheck },
  failed: { label: "ошибка", tone: "bg-slate-200 text-slate-800", Icon: CircleX },
  skipped: { label: "пропущено", tone: "bg-slate-100 text-slate-600", Icon: MinusCircle },
  cancelled: { label: "отменено", tone: "bg-slate-100 text-slate-500", Icon: MinusCircle },
};

const ACTIVE: PushJobState[] = ["queued", "running"];

function JobRow({ job, onCancel, cancelling }: { job: PushJob; onCancel: (id: string) => void; cancelling: boolean }) {
  const meta = STATE[job.state];
  const Icon = meta.Icon;
  return (
    <li className="flex flex-col gap-1 py-2 sm:flex-row sm:items-start sm:justify-between" data-testid={`push-job-${job.hostname}`}>
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-medium text-slate-900">{job.hostname}</span>
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${meta.tone}`}>
            <Icon className={`h-3 w-3 ${job.state === "running" ? "animate-spin" : ""}`} />
            {meta.label}
          </span>
          {job.dry_run && <span className="rounded-full border border-slate-300 px-2 py-0.5 text-[11px] text-slate-500">пробный прогон</span>}
          <span className="text-[11px] text-slate-400">профиль {job.profile === "admin" ? "админ" : "клиент"}</span>
        </p>
        {job.detail && <p className="mt-0.5 break-words text-xs text-slate-500">{job.detail}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2 text-[11px] text-slate-400">
        <span>{relTime(job.finished_at ?? job.started_at ?? job.created_at)}</span>
        {job.state === "queued" && (
          <button
            type="button"
            onClick={() => onCancel(job.id)}
            disabled={cancelling}
            aria-label={`Отменить ${job.hostname}`}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </li>
  );
}

/** The network-push queue: who is waiting, who is being done, how the last ones ended, and whether the
 *  server is configured to run pushes itself (WinRM credentials set). */
export default function PushJobsPanel() {
  const qc = useQueryClient();
  const [showHelp, setShowHelp] = useState(false);

  const { data, isError } = useQuery({
    queryKey: ["remote-push-jobs"],
    queryFn: () => getPushJobs(40),
    retry: false,
    // watch closely while something is in flight, lazily otherwise
    refetchInterval: (query) => (query.state.data?.data.some((j) => ACTIVE.includes(j.state)) ? 4000 : 20000),
  });

  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelPushJob(id),
    onSuccess: (r) => {
      showToast(r.message, "success");
      qc.invalidateQueries({ queryKey: ["remote-push-jobs"] });
    },
    onError: () => showToast("Не удалось отменить: задание уже выполняется", "error"),
  });

  const jobs = data?.data ?? [];
  const waiting = jobs.filter((j) => j.state === "queued").length;
  const running = jobs.filter((j) => j.state === "running").length;
  const configured = data?.configured ?? true; // unknown yet - don't flash "not configured" on first load

  return (
    <section className="app-panel overflow-hidden" aria-label="Раскатка по сети">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/70 px-4 py-3">
        <div className="flex items-center gap-2">
          <Network className="h-4 w-4 text-slate-500" />
          <h3 className="text-sm font-semibold text-slate-800">Раскатка по сети</h3>
          {(waiting > 0 || running > 0) && (
            <span className="text-xs text-slate-500">
              {running > 0 && `${running} выполняется`}
              {running > 0 && waiting > 0 && ", "}
              {waiting > 0 && `${waiting} в очереди`}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs">
          {configured ? (
            <span className="inline-flex items-center gap-1.5 text-emerald-700">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              сетевой push настроен
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-slate-600">
              <span className="h-2 w-2 rounded-full bg-slate-400" />
              сетевой push не настроен
            </span>
          )}
          <button type="button" className="text-[var(--brand)] hover:underline" onClick={() => setShowHelp((v) => !v)} aria-expanded={showHelp}>
            Как это работает
          </button>
        </div>
      </div>

      {showHelp && (
        <div className="space-y-2 border-b border-slate-200 bg-sky-50 px-4 py-3 text-xs text-slate-700">
          <p>
            Сервер сам подключается к машине по WinRM (под сервисной учёткой, заданной в <code className="app-mono">.env</code> как{" "}
            <code className="app-mono">WINRM_ADMIN_USERNAME</code> / <code className="app-mono">WINRM_ADMIN_PASSWORD</code>) и
            запускает ту же команду установки, что и при раскатке через GPO — никакой отдельный раннер не нужен.
          </p>
          <p>
            На машине должен быть включён WinRM (по умолчанию выключен) — см.{" "}
            <code className="app-mono">rustdesk-push/Enable-WinRM-GPO.ps1</code>. Подробности: docs/rustdesk-deployment.md.
          </p>
        </div>
      )}

      <div className="px-4 py-2">
        {isError ? (
          <p className="py-4 text-center text-sm text-slate-500">Не удалось получить очередь.</p>
        ) : jobs.length === 0 ? (
          <p className="py-4 text-center text-sm text-slate-500">
            Заданий пока нет. Нажмите «По сети» на карточке устройства или «Развернуть по сети» над списком.
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {jobs.slice(0, 15).map((job) => (
              <JobRow key={job.id} job={job} onCancel={(id) => cancelMut.mutate(id)} cancelling={cancelMut.isPending} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
