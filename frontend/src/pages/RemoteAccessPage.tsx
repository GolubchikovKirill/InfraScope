import { useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  RefreshCw,
  Search,
  MonitorSmartphone,
  KeyRound,
  ShieldAlert,
  EyeOff,
  Rocket,
  CircleCheck,
  CircleX,
  CircleDashed,
} from "lucide-react";
import { useAuth } from "../auth";
import {
  deployRemoteAccess,
  getRemoteDevices,
  getRemoteJobs,
  rotateRemotePassword,
  rustdeskLink,
  syncRemoteAccess,
  updateRemoteDevice,
  type DeployState,
  type RemoteDevice,
} from "../client";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { showToast } from "../lib/toastBus";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";

const STATE_STYLE: Record<DeployState, string> = {
  unknown: "bg-slate-500/15 text-slate-300",
  not_installed: "bg-slate-500/15 text-slate-300",
  installing: "bg-amber-500/15 text-amber-300",
  installed: "bg-sky-500/15 text-sky-300",
  configured: "bg-emerald-500/15 text-emerald-300",
  drift: "bg-orange-500/15 text-orange-300",
  failed: "bg-rose-500/15 text-rose-300",
  uninstalled: "bg-slate-500/15 text-slate-400",
};
const STATE_LABEL: Record<DeployState, string> = {
  unknown: "не проверено",
  not_installed: "не установлен",
  installing: "устанавливается",
  installed: "установлен",
  configured: "настроен",
  drift: "дрейф конфига",
  failed: "ошибка",
  uninstalled: "удалён",
};

function relTime(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return "только что";
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return `${Math.floor(s / 86400)} дн назад`;
}

export default function RemoteAccessPage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const isSuperuser = Boolean(user?.is_superuser);
  const [q, setQ] = useState("");
  const debouncedQ = useDebouncedValue(q, 300);
  const [location, setLocation] = useState("");
  const [state, setState] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["remote-devices", debouncedQ, location, state],
    queryFn: () =>
      getRemoteDevices({
        q: debouncedQ || undefined,
        location: location || undefined,
        state: state || undefined,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: 20000,
  });
  const { data: jobs } = useQuery({
    queryKey: ["remote-jobs"],
    queryFn: () => getRemoteJobs({ limit: 25 }),
    refetchInterval: 10000,
  });

  const rows = useMemo(() => data?.data ?? [], [data]);
  const locations = useMemo(
    () => Array.from(new Set(rows.map((r) => r.location).filter((x): x is string => !!x))).sort(),
    [rows],
  );
  const summary = useMemo(() => {
    const total = rows.length;
    const configured = rows.filter((r) => r.deploy_state === "configured").length;
    const online = rows.filter((r) => r.online === true).length;
    const failed = rows.filter((r) => r.deploy_state === "failed").length;
    return { total, configured, online, failed };
  }, [rows]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["remote-devices"] });
    qc.invalidateQueries({ queryKey: ["remote-jobs"] });
  };

  const syncMut = useMutation({
    mutationFn: syncRemoteAccess,
    onSuccess: (r) => {
      showToast(r.message, "success");
      invalidate();
    },
    onError: () => showToast("Синхронизация не удалась", "error"),
  });
  const rotateMut = useMutation({
    mutationFn: rotateRemotePassword,
    onSuccess: () => {
      showToast("Ротация пароля поставлена в очередь", "success");
      invalidate();
    },
    onError: () => showToast("Не удалось поставить ротацию", "error"),
  });
  const deployMut = useMutation({
    mutationFn: deployRemoteAccess,
    onSuccess: (r) => {
      showToast(`Задач создано: ${r.count}`, "success");
      invalidate();
    },
    onError: () => showToast("Не удалось поставить раскатку", "error"),
  });
  const toggleMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<RemoteDevice> }) =>
      updateRemoteDevice(id, payload),
    onSuccess: () => invalidate(),
  });

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        {[
          { label: "Устройств", value: summary.total },
          { label: "Настроено", value: summary.configured },
          { label: "Онлайн", value: summary.online },
          { label: "Ошибок", value: summary.failed },
        ].map((s) => (
          <Card key={s.label}>
            <CardContent className="py-3">
              <div className="text-xs text-slate-400">{s.label}</div>
              <div className="text-2xl font-semibold">{s.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-slate-400" />
            <Input
              className="pl-8"
              placeholder="hostname / RustDesk ID"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <select
            className="rounded-md border border-slate-700 bg-slate-900 px-2 py-2 text-sm"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
          >
            <option value="">Все точки</option>
            {locations.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
          <select
            className="rounded-md border border-slate-700 bg-slate-900 px-2 py-2 text-sm"
            value={state}
            onChange={(e) => setState(e.target.value)}
          >
            <option value="">Любой статус</option>
            {Object.keys(STATE_LABEL).map((k) => (
              <option key={k} value={k}>
                {STATE_LABEL[k as DeployState]}
              </option>
            ))}
          </select>
          <div className="ml-auto flex gap-2">
            <Button variant="secondary" onClick={() => syncMut.mutate()} disabled={syncMut.isPending}>
              <RefreshCw className={`mr-1 h-4 w-4 ${syncMut.isPending ? "animate-spin" : ""}`} />
              Синхронизировать
            </Button>
            {isSuperuser && (
              <Button
                onClick={() =>
                  deployMut.mutate(
                    location
                      ? { action: "reconfigure", location }
                      : { action: "reconfigure", all_managed: true },
                  )
                }
                disabled={deployMut.isPending}
              >
                <Rocket className="mr-1 h-4 w-4" />
                Раскатать{location ? ` · ${location}` : " · всё"}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-left text-xs uppercase text-slate-400">
              <tr>
                <th className="px-3 py-2">Хост</th>
                <th className="px-3 py-2">RustDesk ID</th>
                <th className="px-3 py-2">Точка</th>
                <th className="px-3 py-2">Статус</th>
                <th className="px-3 py-2">Деплой</th>
                <th className="px-3 py-2">Пароль</th>
                <th className="px-3 py-2">Защита</th>
                <th className="px-3 py-2 text-right">Действия</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-slate-400">
                    Загрузка…
                  </td>
                </tr>
              )}
              {rows.map((d) => (
                <tr key={d.id} className="border-t border-slate-800/70">
                  <td className="px-3 py-2 font-medium">{d.hostname}</td>
                  <td className="px-3 py-2 font-mono text-xs">{d.rustdesk_id ?? "—"}</td>
                  <td className="px-3 py-2">{d.location ?? "—"}</td>
                  <td className="px-3 py-2">
                    <span className="inline-flex items-center gap-1">
                      {d.online === true ? (
                        <CircleCheck className="h-4 w-4 text-emerald-400" />
                      ) : d.online === false ? (
                        <CircleX className="h-4 w-4 text-slate-500" />
                      ) : (
                        <CircleDashed className="h-4 w-4 text-slate-600" />
                      )}
                      <span className="text-xs text-slate-400">{relTime(d.last_seen_at)}</span>
                    </span>
                    {d.logged_in_user && (
                      <div className="text-[11px] text-slate-500">{d.logged_in_user}</div>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs ${STATE_STYLE[d.deploy_state]}`}
                      title={d.last_error ?? d.deploy_detail ?? ""}
                    >
                      {STATE_LABEL[d.deploy_state]}
                    </span>
                    {d.installed_version && (
                      <span className="ml-1 text-[11px] text-slate-500">v{d.installed_version}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {d.has_password ? (
                      <span className="text-xs text-emerald-400" title={`ротация: ${relTime(d.password_rotated_at)}`}>
                        задан
                      </span>
                    ) : (
                      <span className="text-xs text-slate-500">нет</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex gap-1">
                      <button
                        title="Скрыт от пользователя"
                        onClick={() =>
                          isSuperuser &&
                          toggleMut.mutate({ id: d.id, payload: { desired_hidden: !d.desired_hidden } })
                        }
                        className={d.desired_hidden ? "text-sky-400" : "text-slate-600"}
                      >
                        <EyeOff className="h-4 w-4" />
                      </button>
                      <button
                        title="Запрет исходящих подключений"
                        onClick={() =>
                          isSuperuser &&
                          toggleMut.mutate({
                            id: d.id,
                            payload: { desired_block_outgoing: !d.desired_block_outgoing },
                          })
                        }
                        className={d.desired_block_outgoing ? "text-sky-400" : "text-slate-600"}
                      >
                        <ShieldAlert className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-1">
                      <a href={rustdeskLink(d.rustdesk_id ?? d.hostname)}>
                        <Button variant="secondary" className="h-7 px-2">
                          <MonitorSmartphone className="mr-1 h-3.5 w-3.5" />
                          Подключиться
                        </Button>
                      </a>
                      {isSuperuser && (
                        <>
                          <Button
                            variant="secondary"
                            className="h-7 px-2"
                            title="Ротировать пароль"
                            onClick={() => rotateMut.mutate(d.id)}
                          >
                            <KeyRound className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="secondary"
                            className="h-7 px-2"
                            title="Переприменить конфиг"
                            onClick={() => deployMut.mutate({ action: "reconfigure", device_ids: [d.id] })}
                          >
                            <Rocket className="h-3.5 w-3.5" />
                          </Button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {!isLoading && rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-slate-400">
                    Нет устройств. Нажмите «Синхронизировать».
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Задачи раскатки</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-left text-xs uppercase text-slate-400">
              <tr>
                <th className="px-3 py-2">Хост</th>
                <th className="px-3 py-2">Действие</th>
                <th className="px-3 py-2">Статус</th>
                <th className="px-3 py-2">Когда</th>
                <th className="px-3 py-2">Детали</th>
              </tr>
            </thead>
            <tbody>
              {(jobs?.data ?? []).map((j) => (
                <tr key={j.id} className="border-t border-slate-800/70">
                  <td className="px-3 py-2">{j.hostname}</td>
                  <td className="px-3 py-2">{j.action}</td>
                  <td className="px-3 py-2">{j.status}</td>
                  <td className="px-3 py-2 text-xs text-slate-400">{relTime(j.created_at)}</td>
                  <td className="px-3 py-2 text-xs text-slate-400">{j.result_detail ?? "—"}</td>
                </tr>
              ))}
              {(jobs?.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-4 text-center text-slate-500">
                    Задач нет
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
