import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  CircleHelp,
  CircleX,
  Loader2,
  Pencil,
  PlayCircle,
  RefreshCw,
  Search,
  ServerCog,
  ShieldCheck,
  TriangleAlert,
  X,
} from "lucide-react";
import {
  checkAllHonestSignTargets,
  checkHonestSignTarget,
  getHonestSignTargets,
  initializeHonestSignTarget,
  updateHonestSignTargetIp,
  type HonestSignInitializeResult,
  type HonestSignStatus,
  type HonestSignStatusesResponse,
  type HonestSignTarget,
} from "../client";
import { useAuth } from "../auth";
import { showToast } from "../lib/toastBus";
import { apiErrorMessage } from "../lib/apiError";

const STATUS_QUERY_KEY = ["honest-sign", "statuses"] as const;

export default function HonestSignPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isSuperuser = user?.is_superuser ?? false;
  const [targetToInitialize, setTargetToInitialize] = useState<HonestSignTarget | null>(null);
  const [lastResult, setLastResult] = useState<HonestSignInitializeResult | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [locationFilter, setLocationFilter] = useState("");
  const [editingIpFor, setEditingIpFor] = useState<string | null>(null);
  const [newIpValue, setNewIpValue] = useState("");

  const targetsQuery = useQuery({
    queryKey: ["honest-sign", "targets"],
    queryFn: getHonestSignTargets,
  });
  const statusesQuery = useQuery({
    queryKey: STATUS_QUERY_KEY,
    queryFn: checkAllHonestSignTargets,
    enabled: targetsQuery.data?.status_configured === true,
    retry: false,
  });

  const updateOneStatus = (status: HonestSignStatus) => {
    queryClient.setQueryData<HonestSignStatusesResponse>(STATUS_QUERY_KEY, (current) => {
      const rows = current?.data ?? [];
      const exists = rows.some((item) => item.host === status.host);
      const data = exists ? rows.map((item) => (item.host === status.host ? status : item)) : [...rows, status];
      return { data, count: data.length };
    });
  };
  const checkOneMutation = useMutation({
    mutationFn: checkHonestSignTarget,
    onSuccess: updateOneStatus,
  });
  const initializeMutation = useMutation({
    mutationFn: initializeHonestSignTarget,
    onSuccess: async (result) => {
      setLastResult(result);
      setTargetToInitialize(null);
      await statusesQuery.refetch();
    },
  });
  const updateIpMutation = useMutation({
    mutationFn: ({ originalHost, newIp }: { originalHost: string; newIp: string }) =>
      updateHonestSignTargetIp(originalHost, newIp),
    onSuccess: async () => {
      setEditingIpFor(null);
      setNewIpValue("");
      showToast("IP кассы обновлён", "success");
      await targetsQuery.refetch();
      await statusesQuery.refetch();
    },
    onError: (error) => showToast(apiErrorMessage(error, "Не удалось изменить IP"), "error"),
  });

  const startEditingIp = (target: HonestSignTarget) => {
    setEditingIpFor(target.original_host);
    setNewIpValue(target.host);
  };
  const cancelEditingIp = () => {
    setEditingIpFor(null);
    setNewIpValue("");
  };
  const confirmEditingIp = (originalHost: string) => {
    if (!newIpValue.trim()) return;
    updateIpMutation.mutate({ originalHost, newIp: newIpValue.trim() });
  };

  const targets = targetsQuery.data?.data ?? [];
  const statuses = statusesQuery.data?.data ?? [];
  const locations = useMemo(
    () => [...new Set(targets.map((target) => target.label))].sort((a, b) => a.localeCompare(b, "ru", { numeric: true })),
    [targets],
  );
  const visibleTargets = useMemo(() => {
    const needle = searchQuery.trim().toLocaleLowerCase("ru-RU");
    return targets.filter((target) => {
      if (locationFilter && target.label !== locationFilter) return false;
      if (!needle) return true;
      return [target.host, target.label, target.hostname || ""]
        .some((value) => value.toLocaleLowerCase("ru-RU").includes(needle));
    });
  }, [locationFilter, searchQuery, targets]);
  const byHost = useMemo(() => new Map(statuses.map((status) => [status.host, status])), [statuses]);
  const hostnameCount = targets.filter((target) => target.hostname).length;
  const readyCount = statuses.filter((status) => status.ready).length;
  const initializingCount = statuses.filter((status) => status.status.toLocaleLowerCase("ru-RU") === "initialization").length;
  const errorCount = statuses.filter((status) => !status.reachable || status.status.startsWith("HTTP_")).length;
  const isCheckingAll = statusesQuery.isFetching;

  if (targetsQuery.isLoading) {
    return <div className="app-panel h-48 app-skeleton" />;
  }
  if (targetsQuery.isError) {
    return <div className="app-panel p-8 text-center text-rose-600">Не удалось загрузить настройки Честного знака.</div>;
  }

  return (
    <div className="space-y-5">
      <section className="app-panel overflow-hidden">
        <div className="flex flex-col gap-4 border-b border-slate-200 bg-slate-50/70 p-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="rounded-xl bg-emerald-100 p-2.5 text-emerald-700"><ShieldCheck className="h-5 w-5" /></div>
            <div>
              <h2 className="font-semibold text-slate-900">Локальный модуль «Честный знак»</h2>
              <p className="mt-1 max-w-2xl text-sm text-slate-500">Проверка API v2 на кассах и безопасный запуск удалённой инициализации. Готовый модуль повторно не активируется.</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => statusesQuery.refetch()}
            disabled={!targetsQuery.data?.status_configured || isCheckingAll}
            className="app-btn-primary inline-flex items-center justify-center gap-2 px-4 py-2 text-sm disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${isCheckingAll ? "animate-spin" : ""}`} />
            Проверить все
          </button>
        </div>

        {!targetsQuery.data?.status_configured && (
          <div className="m-5 flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0" />
            <div><div className="font-semibold">Интеграция ещё не настроена на сервере</div><div className="mt-1 text-amber-800">Нужны список IP-адресов и учётные данные Local Module в серверном `.env`.</div></div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 p-5 sm:grid-cols-5">
          <StatCard label="Касс в списке" value={targets.length} />
          <StatCard label="Hostname найден" value={hostnameCount} tone="sky" />
          <StatCard label="Готовы" value={readyCount} tone="green" />
          <StatCard label="Инициализация" value={initializingCount} tone="sky" />
          <StatCard label="Недоступны" value={errorCount} tone="red" />
        </div>
      </section>

      {lastResult && (
        <div className={`app-panel flex gap-3 p-4 text-sm ${lastResult.result === "READY" || lastResult.result === "ALREADY_READY" ? "text-emerald-700" : lastResult.result === "INIT_FAILED" || lastResult.result === "ERROR" ? "text-rose-700" : "text-sky-700"}`}>
          <ResultIcon result={lastResult.result} />
          <div><div className="font-semibold">{lastResult.host}: {resultLabel(lastResult.result)}</div><div className="mt-1">{lastResult.message}</div></div>
        </div>
      )}

      {statusesQuery.isError && targetsQuery.data?.status_configured && (
        <div className="app-panel p-5 text-sm text-rose-600">Не удалось выполнить проверку. Проверьте доступность сети сервера и настройки интеграции.</div>
      )}

      <div className="app-panel flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">Поиск кассы</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="IP, hostname или магазин"
            className="app-input w-full py-2 pl-9 pr-3 text-sm"
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-500">
          <span>Магазин</span>
          <select
            value={locationFilter}
            onChange={(event) => setLocationFilter(event.target.value)}
            className="app-input min-w-32 px-3 py-2 text-sm text-slate-700"
          >
            <option value="">Все</option>
            {locations.map((location) => <option key={location} value={location}>{location}</option>)}
          </select>
        </label>
        <div className="text-xs text-slate-500">Показано: {visibleTargets.length} из {targets.length}</div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {visibleTargets.map((target) => {
          const status = byHost.get(target.host);
          const checkingThis = checkOneMutation.isPending && checkOneMutation.variables === target.host;
          const initializingThis = initializeMutation.isPending && initializeMutation.variables === target.host;
          const isEditingIp = editingIpFor === target.original_host;
          const savingIp = updateIpMutation.isPending && updateIpMutation.variables?.originalHost === target.original_host;
          return (
            <article key={target.original_host} className="app-panel p-5">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex min-w-0 items-start gap-3">
                  <div className={`rounded-xl p-2.5 ${status?.ready ? "bg-emerald-100 text-emerald-700" : status?.reachable === false ? "bg-rose-100 text-rose-700" : "bg-slate-100 text-slate-600"}`}><ServerCog className="h-5 w-5" /></div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      {isEditingIp ? (
                        <div className="flex items-center gap-1.5">
                          <input
                            type="text"
                            value={newIpValue}
                            onChange={(event) => setNewIpValue(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") confirmEditingIp(target.original_host);
                              if (event.key === "Escape") cancelEditingIp();
                            }}
                            autoFocus
                            disabled={savingIp}
                            className="app-input w-36 px-2 py-1 font-mono text-sm"
                          />
                          <button
                            type="button"
                            title="Сохранить"
                            onClick={() => confirmEditingIp(target.original_host)}
                            disabled={savingIp}
                            className="rounded-lg p-1 text-emerald-600 hover:bg-emerald-50 disabled:opacity-40"
                          >
                            {savingIp ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                          </button>
                          <button
                            type="button"
                            title="Отмена"
                            onClick={cancelEditingIp}
                            disabled={savingIp}
                            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 disabled:opacity-40"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        </div>
                      ) : (
                        <>
                          <h3 className="font-semibold text-slate-900">{target.host}</h3>
                          {isSuperuser && (
                            <button
                              type="button"
                              title="Изменить IP"
                              onClick={() => startEditingIp(target)}
                              className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </>
                      )}
                      <StatusBadge status={status} />
                    </div>
                    <p className="mt-1 text-sm text-slate-500">{target.label}</p>
                    {target.hostname && <p className="mt-1 font-mono text-xs font-medium text-slate-700">{target.hostname}</p>}
                    <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
                      <Field label="Версия" value={status?.version || "—"} />
                      <Field label="API" value="v2 :5995" />
                      <Field label="Проверено" value={status ? new Date(status.checked_at).toLocaleString("ru-RU") : "—"} />
                      <Field label="Состояние" value={status?.status || "не проверено"} />
                    </div>
                    {status?.message && <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">{status.message}</div>}
                  </div>
                </div>
                <div className="flex shrink-0 gap-2">
                  <button
                    type="button"
                    aria-label={`Проверить ${target.host}`}
                    title="Проверить статус"
                    onClick={() => checkOneMutation.mutate(target.host)}
                    disabled={!targetsQuery.data?.status_configured || checkingThis || initializeMutation.isPending}
                    className="app-btn-secondary inline-flex h-10 w-10 items-center justify-center disabled:opacity-40"
                  >
                    {checkingThis ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  </button>
                  {isSuperuser && (
                    <button
                      type="button"
                      onClick={() => setTargetToInitialize(target)}
                      disabled={!targetsQuery.data?.initialization_configured || status?.ready || initializeMutation.isPending}
                      className="app-btn-primary inline-flex items-center gap-2 px-3 py-2 text-sm disabled:opacity-40"
                    >
                      {initializingThis ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
                      Активировать
                    </button>
                  )}
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {targets.length === 0 && <div className="app-empty p-10 text-center text-slate-500">Список касс для Честного знака пуст.</div>}
      {targets.length > 0 && visibleTargets.length === 0 && <div className="app-empty p-10 text-center text-slate-500">По заданным условиям кассы не найдены.</div>}

      {targetToInitialize && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="app-panel w-full max-w-lg p-5">
            <div className="flex items-start gap-3"><div className="rounded-xl bg-amber-100 p-2 text-amber-700"><TriangleAlert className="h-5 w-5" /></div><div><h2 className="font-semibold text-slate-900">Инициализировать Local Module?</h2><p className="mt-2 text-sm text-slate-600">На кассу <strong>{targetToInitialize.host}</strong> будет отправлен запрос `/api/v2/init`. Перед запуском сервер ещё раз проверит текущий статус.</p></div></div>
            {initializeMutation.isError && <div className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-700">Запрос инициализации завершился ошибкой.</div>}
            <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={() => setTargetToInitialize(null)} disabled={initializeMutation.isPending} className="app-btn-secondary px-4 py-2 text-sm">Отмена</button><button type="button" onClick={() => initializeMutation.mutate(targetToInitialize.host)} disabled={initializeMutation.isPending} className="app-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50">{initializeMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}Подтвердить активацию</button></div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status?: HonestSignStatus }) {
  if (!status) return <span className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">не проверено</span>;
  if (status.ready) return <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-1 text-xs font-medium text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" />готов</span>;
  if (!status.reachable) return <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-1 text-xs font-medium text-rose-700"><CircleX className="h-3.5 w-3.5" />недоступен</span>;
  if (status.status.toLocaleLowerCase("ru-RU") === "initialization") return <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-1 text-xs font-medium text-sky-700"><Loader2 className="h-3.5 w-3.5 animate-spin" />инициализация</span>;
  return <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-800"><CircleHelp className="h-3.5 w-3.5" />{status.status}</span>;
}

function StatCard({ label, value, tone = "default" }: { label: string; value: number; tone?: "default" | "green" | "sky" | "red" }) {
  const color = tone === "green" ? "text-emerald-700" : tone === "sky" ? "text-sky-700" : tone === "red" ? "text-rose-700" : "text-slate-900";
  return <div className="app-stat px-4 py-3"><div className={`text-2xl font-bold ${color}`}>{value}</div><div className="mt-0.5 text-xs text-slate-500">{label}</div></div>;
}

function Field({ label, value }: { label: string; value: string }) { return <div><span className="text-slate-400">{label}: </span><span className="text-slate-700">{value}</span></div>; }

function resultLabel(result: string) {
  if (result === "READY") return "модуль готов";
  if (result === "ALREADY_READY") return "уже был готов";
  if (result === "INITIALIZING") return "инициализация выполняется";
  if (result === "REQUEST_ACCEPTED") return "запрос принят";
  return "ошибка инициализации";
}

function ResultIcon({ result }: { result: string }) {
  if (result === "READY" || result === "ALREADY_READY") return <CheckCircle2 className="h-5 w-5 shrink-0" />;
  if (result === "INIT_FAILED" || result === "ERROR") return <CircleX className="h-5 w-5 shrink-0" />;
  return <Loader2 className="h-5 w-5 shrink-0 animate-spin" />;
}
