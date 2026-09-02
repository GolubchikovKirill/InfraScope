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
  Copy,
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
  type SourceKind,
} from "../client";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { showToast } from "../lib/toastBus";
import { Button } from "../components/ui/Button";

type BadgeTone = "default" | "green" | "red" | "amber" | "sky" | "violet";
const badgeTone: Record<BadgeTone, string> = {
  default: "bg-slate-100 text-slate-600",
  green: "bg-emerald-100 text-emerald-700",
  red: "bg-rose-100 text-rose-700",
  amber: "bg-amber-100 text-amber-800",
  sky: "bg-sky-100 text-sky-700",
  violet: "bg-violet-100 text-violet-700",
};
const STATE: Record<DeployState, { label: string; tone: BadgeTone }> = {
  unknown: { label: "не проверено", tone: "default" },
  not_installed: { label: "не установлен", tone: "default" },
  installing: { label: "устанавливается", tone: "amber" },
  installed: { label: "установлен", tone: "sky" },
  configured: { label: "настроен", tone: "green" },
  drift: { label: "дрейф конфига", tone: "amber" },
  failed: { label: "ошибка", tone: "red" },
  uninstalled: { label: "удалён", tone: "default" },
};

const KIND: Record<SourceKind, { label: string; short: string; tone: BadgeTone }> = {
  cash_register: { label: "Кассы", short: "касса", tone: "violet" },
  computer: { label: "Компьютеры", short: "ПК", tone: "sky" },
  media_player: { label: "Медиаплееры", short: "неттоп", tone: "amber" },
};

function relTime(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return "только что";
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return `${Math.floor(s / 86400)} дн назад`;
}

function Badge({ children, tone = "default" }: { children: React.ReactNode; tone?: BadgeTone }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${badgeTone[tone]}`}>
      {children}
    </span>
  );
}

export default function RemoteAccessPage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const isSuperuser = Boolean(user?.is_superuser);
  const [q, setQ] = useState("");
  const debouncedQ = useDebouncedValue(q, 300);
  const [location, setLocation] = useState("");
  const [kind, setKind] = useState<"" | SourceKind>("");
  const [state, setState] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["remote-devices", debouncedQ, location, kind, state],
    queryFn: () =>
      getRemoteDevices({
        q: debouncedQ || undefined,
        location: location || undefined,
        source_kind: kind || undefined,
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
  const summary = useMemo(
    () => ({
      total: rows.length,
      configured: rows.filter((r) => r.deploy_state === "configured").length,
      online: rows.filter((r) => r.online === true).length,
      failed: rows.filter((r) => r.deploy_state === "failed").length,
    }),
    [rows],
  );

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

  const copyId = (id: string) => {
    navigator.clipboard?.writeText(id).then(
      () => showToast(`ID скопирован: ${id}`, "success"),
      () => showToast("Не удалось скопировать", "error"),
    );
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        {[
          { label: "Устройств", value: summary.total },
          { label: "Настроено", value: summary.configured },
          { label: "Онлайн", value: summary.online },
          { label: "Ошибок", value: summary.failed },
        ].map((s) => (
          <div key={s.label} className="app-stat px-4 py-3">
            <div className="text-2xl font-bold text-gray-900">{s.value}</div>
            <div className="mt-0.5 text-xs text-gray-500">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="app-panel overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-slate-50/70 px-4 py-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-slate-400" />
            <input
              className="app-input w-56 pl-8 pr-3 py-2 text-sm"
              placeholder="hostname / RustDesk ID"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <select
            className="app-input px-3 py-2 text-sm text-slate-700"
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
            className="app-input px-3 py-2 text-sm text-slate-700"
            value={kind}
            onChange={(e) => setKind(e.target.value as "" | SourceKind)}
          >
            <option value="">Все классы</option>
            {(Object.keys(KIND) as SourceKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND[k].label}
              </option>
            ))}
          </select>
          <select
            className="app-input px-3 py-2 text-sm text-slate-700"
            value={state}
            onChange={(e) => setState(e.target.value)}
          >
            <option value="">Любой статус</option>
            {(Object.keys(STATE) as DeployState[]).map((k) => (
              <option key={k} value={k}>
                {STATE[k].label}
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
                  deployMut.mutate({
                    action: "reconfigure",
                    all_managed: true,
                    ...(location ? { location } : {}),
                    ...(kind ? { source_kind: kind } : {}),
                  })
                }
                disabled={deployMut.isPending}
              >
                <Rocket className="mr-1 h-4 w-4" />
                Раскатать
                {location || kind
                  ? ` · ${[kind ? KIND[kind].label : null, location].filter(Boolean).join(" / ")}`
                  : " · всё"}
              </Button>
            )}
          </div>
        </div>

        <div className="overflow-x-auto app-compact-scroll">
          <table className="app-table min-w-full">
            <thead>
              <tr>
                <th>Хост</th>
                <th>RustDesk ID</th>
                <th>Класс</th>
                <th>Точка</th>
                <th>Статус</th>
                <th>Деплой</th>
                <th>Пароль</th>
                <th>Защита</th>
                <th className="text-right">Действия</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={9} className="py-10 text-center text-gray-400">
                    Загрузка…
                  </td>
                </tr>
              )}
              {rows.map((d) => (
                <tr key={d.id}>
                  <td className="font-medium text-slate-800">{d.hostname}</td>
                  <td>
                    <div className="flex items-center gap-1.5">
                      <span className="app-mono text-xs">{d.rustdesk_id ?? "—"}</span>
                      {d.rustdesk_id && (
                        <button
                          onClick={() => copyId(d.rustdesk_id!)}
                          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-[var(--brand)]"
                          title="Скопировать ID"
                        >
                          <Copy className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </td>
                  <td>
                    <Badge tone={KIND[d.source_kind].tone}>{KIND[d.source_kind].short}</Badge>
                  </td>
                  <td>{d.location ?? "—"}</td>
                  <td>
                    <span className="inline-flex items-center gap-1">
                      {d.online === true ? (
                        <CircleCheck className="h-4 w-4 text-emerald-500" />
                      ) : d.online === false ? (
                        <CircleX className="h-4 w-4 text-slate-400" />
                      ) : (
                        <CircleDashed className="h-4 w-4 text-slate-300" />
                      )}
                      <span className="text-xs text-gray-500">{relTime(d.last_seen_at)}</span>
                    </span>
                    {d.logged_in_user && (
                      <div className="app-card-meta app-mono">{d.logged_in_user}</div>
                    )}
                  </td>
                  <td>
                    <span title={d.last_error ?? d.deploy_detail ?? ""}>
                      <Badge tone={STATE[d.deploy_state].tone}>{STATE[d.deploy_state].label}</Badge>
                    </span>
                    {d.installed_version && (
                      <span className="ml-1 text-[11px] text-gray-400">v{d.installed_version}</span>
                    )}
                  </td>
                  <td>
                    {d.has_password ? (
                      <span
                        className="text-xs text-emerald-600"
                        title={`ротация: ${relTime(d.password_rotated_at)}`}
                      >
                        задан
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">нет</span>
                    )}
                  </td>
                  <td>
                    <div className="flex gap-1">
                      <button
                        title={d.desired_hidden ? "Скрыт от пользователя" : "Виден пользователю"}
                        disabled={!isSuperuser}
                        onClick={() =>
                          toggleMut.mutate({ id: d.id, payload: { desired_hidden: !d.desired_hidden } })
                        }
                        className={d.desired_hidden ? "text-[var(--brand)]" : "text-slate-300"}
                      >
                        <EyeOff className="h-4 w-4" />
                      </button>
                      <button
                        title={
                          d.desired_block_outgoing
                            ? "Исходящие подключения запрещены"
                            : "Исходящие подключения разрешены"
                        }
                        disabled={!isSuperuser}
                        onClick={() =>
                          toggleMut.mutate({
                            id: d.id,
                            payload: { desired_block_outgoing: !d.desired_block_outgoing },
                          })
                        }
                        className={d.desired_block_outgoing ? "text-[var(--brand)]" : "text-slate-300"}
                      >
                        <ShieldAlert className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                  <td>
                    <div className="flex justify-end gap-1">
                      <a href={rustdeskLink(d.rustdesk_id ?? d.hostname)}>
                        <Button variant="secondary" size="sm" className="!px-2.5 !text-xs">
                          <MonitorSmartphone className="mr-1 h-3.5 w-3.5" />
                          Подключиться
                        </Button>
                      </a>
                      {isSuperuser && (
                        <>
                          <Button
                            variant="secondary"
                            size="sm"
                            className="!px-2"
                            title="Ротировать пароль"
                            onClick={() => rotateMut.mutate(d.id)}
                          >
                            <KeyRound className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            className="!px-2"
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
                  <td colSpan={9} className="py-10 text-center text-gray-400">
                    Нет устройств. Нажмите «Синхронизировать».
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="app-panel overflow-hidden">
        <div className="border-b border-slate-200 bg-slate-50/70 px-4 py-3 text-sm font-semibold text-slate-700">
          Задачи раскатки
        </div>
        <div className="overflow-x-auto app-compact-scroll">
          <table className="app-table min-w-full">
            <thead>
              <tr>
                <th>Хост</th>
                <th>Действие</th>
                <th>Статус</th>
                <th>Когда</th>
                <th>Детали</th>
              </tr>
            </thead>
            <tbody>
              {(jobs?.data ?? []).map((j) => (
                <tr key={j.id}>
                  <td>{j.hostname}</td>
                  <td className="app-mono text-xs">{j.action}</td>
                  <td>
                    <Badge
                      tone={
                        j.status === "done"
                          ? "green"
                          : j.status === "failed"
                            ? "red"
                            : j.status === "running" || j.status === "claimed"
                              ? "amber"
                              : "default"
                      }
                    >
                      {j.status}
                    </Badge>
                  </td>
                  <td className="text-xs text-gray-500">{relTime(j.created_at)}</td>
                  <td className="text-xs text-gray-500">{j.result_detail ?? "—"}</td>
                </tr>
              ))}
              {(jobs?.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-gray-400">
                    Задач нет
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
