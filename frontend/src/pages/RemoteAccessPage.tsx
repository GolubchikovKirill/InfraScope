import { useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  RefreshCw,
  Search,
  MonitorSmartphone,
  KeyRound,
  ShieldAlert,
  EyeOff,
  BookUser,
  Copy,
  Rocket,
  Terminal,
} from "lucide-react";
import { useAuth } from "../auth";
import {
  getConsoleConnections,
  getRemoteDevices,
  requestDeploy,
  rotateRemotePassword,
  rustdeskLink,
  syncAddressBook,
  syncRemoteAccess,
  updateRemoteDevice,
  type RemoteDevice,
  type SourceKind,
} from "../client";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { showToast } from "../lib/toastBus";
import { relTime } from "../lib/relTime";
import { Button } from "../components/ui/Button";
import { ReadinessChip, deviceReadinessDetail } from "../components/RemoteAccessStatus";
import DeployCommandModal from "../components/DeployCommandModal";
import ConsoleAccountsPanel from "../components/ConsoleAccountsPanel";

type BadgeTone = "default" | "green" | "red" | "amber" | "sky" | "violet";
const badgeTone: Record<BadgeTone, string> = {
  default: "bg-slate-100 text-slate-600",
  green: "bg-emerald-100 text-emerald-700",
  red: "bg-rose-100 text-rose-700",
  amber: "bg-amber-100 text-amber-800",
  sky: "bg-sky-100 text-sky-700",
  violet: "bg-violet-100 text-violet-700",
};

const KIND: Record<SourceKind, { label: string; short: string; tone: BadgeTone }> = {
  cash_register: { label: "Кассы", short: "касса", tone: "violet" },
  computer: { label: "Компьютеры", short: "ПК", tone: "sky" },
  media_player: { label: "Медиаплееры", short: "неттоп", tone: "amber" },
};

type TabKey = "devices" | "accounts" | "connections";
const TABS: { key: TabKey; label: string }[] = [
  { key: "devices", label: "Устройства" },
  { key: "accounts", label: "Админы" },
  { key: "connections", label: "Подключения" },
];

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
  const [tab, setTab] = useState<TabKey>("devices");
  const [q, setQ] = useState("");
  const debouncedQ = useDebouncedValue(q, 300);
  const [location, setLocation] = useState("");
  const [kind, setKind] = useState<"" | SourceKind>("");
  const [deployModalOpen, setDeployModalOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["remote-devices", debouncedQ, location, kind],
    queryFn: () =>
      getRemoteDevices({
        q: debouncedQ || undefined,
        location: location || undefined,
        source_kind: kind || undefined,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: 20000,
  });
  const consoleConns = useQuery({
    queryKey: ["rd-console", "connections"],
    queryFn: () => getConsoleConnections(200),
    retry: false,
    refetchInterval: 30000,
    enabled: tab === "connections" || tab === "devices",
  });
  // the console-side queries this page still makes all fail the same way when
  // the token is missing/dead, so one of them stands in for "console down"
  const consoleDown = consoleConns.isError;

  const rows = useMemo(() => data?.data ?? [], [data]);
  const locations = useMemo(
    () => Array.from(new Set(rows.map((r) => r.location).filter((x): x is string => !!x))).sort(),
    [rows],
  );
  const summary = useMemo(
    () => ({
      total: rows.length,
      ready: rows.filter((r) => r.readiness === "ready").length,
      inBook: rows.filter((r) => r.in_address_book).length,
      noId: rows.filter((r) => !r.rustdesk_id).length,
    }),
    [rows],
  );

  const invalidate = () => qc.invalidateQueries({ queryKey: ["remote-devices"] });

  const syncMut = useMutation({
    mutationFn: syncRemoteAccess,
    onSuccess: (r) => {
      showToast(r.message, "success");
      invalidate();
    },
    onError: () => showToast("Синхронизация не удалась", "error"),
  });
  const abMut = useMutation({
    mutationFn: syncAddressBook,
    onSuccess: (r) => {
      showToast(r.message, "success");
      invalidate();
    },
    onError: () => showToast("Не удалось синхронизировать книгу адресов", "error"),
  });
  const rotateMut = useMutation({
    mutationFn: rotateRemotePassword,
    onSuccess: () => {
      showToast("Пароль сгенерирован — применится при следующем прогоне раскатки", "success");
      invalidate();
    },
    onError: () => showToast("Не удалось сгенерировать пароль", "error"),
  });
  const toggleMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<RemoteDevice> }) =>
      updateRemoteDevice(id, payload),
    onSuccess: () => invalidate(),
  });
  const deployMut = useMutation({
    mutationFn: (id: string) => requestDeploy(id),
    onSuccess: (dev) => {
      showToast(`${dev.hostname}: ждёт запуска скрипта на машине`, "success");
      invalidate();
      setDeployModalOpen(true);
    },
    onError: () => showToast("Не удалось запросить развёртывание", "error"),
  });

  const bulkAb = () => {
    const scope = [kind ? KIND[kind].label : null, location].filter(Boolean).join(" / ") || "все управляемые";
    if (!window.confirm(`Протолкнуть в общую книгу адресов: ${scope}?`)) return;
    abMut.mutate({
      ...(location ? { location } : {}),
      ...(kind ? { source_kind: kind } : {}),
    });
  };

  const copyId = (id: string) => {
    navigator.clipboard?.writeText(id).then(
      () => showToast(`ID скопирован: ${id}`, "success"),
      () => showToast("Не удалось скопировать", "error"),
    );
  };

  return (
    <div className="space-y-4">
      <div className="app-tabbar flex w-fit max-w-full gap-1 overflow-x-auto app-compact-scroll p-1.5">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`app-tab px-4 py-2 text-sm font-medium ${
              tab === key ? "active" : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "devices" && (
        <div className="space-y-4">
          {consoleDown && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
              Консоль RustDesk не подключена — статусы «онлайн» и книга адресов недоступны. Укажите{" "}
              <code className="app-mono">RUSTDESK_API_TOKEN</code> в <code className="app-mono">.env</code> сервера.
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-4">
            {[
              { label: "Устройств", value: summary.total },
              { label: "Готово к подключению", value: summary.ready },
              { label: "В книге адресов", value: summary.inBook },
              { label: "Без RustDesk ID", value: summary.noId },
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
              <div className="ml-auto flex gap-2">
                <Button variant="secondary" onClick={() => syncMut.mutate()} disabled={syncMut.isPending}>
                  <RefreshCw className={`mr-1 h-4 w-4 ${syncMut.isPending ? "animate-spin" : ""}`} />
                  Синхронизировать
                </Button>
                {isSuperuser && (
                  <Button variant="secondary" onClick={() => setDeployModalOpen(true)}>
                    <Terminal className="mr-1 h-4 w-4" />
                    Команда для KSC
                  </Button>
                )}
                {isSuperuser && (
                  <Button onClick={bulkAb} disabled={abMut.isPending || consoleDown}>
                    <BookUser className="mr-1 h-4 w-4" />
                    В книгу адресов
                    {location || kind
                      ? ` · ${[kind ? KIND[kind].label : null, location].filter(Boolean).join(" / ")}`
                      : ""}
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
                    <th>Готовность</th>
                    <th>Пароль</th>
                    <th>Защита</th>
                    <th className="text-right">Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {isLoading && (
                    <tr>
                      <td colSpan={8} className="py-10 text-center text-gray-400">
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
                        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-gray-400">
                          {d.installed_version && <span>v{d.installed_version}</span>}
                          {d.in_address_book && <span className="text-emerald-600">в книге</span>}
                        </div>
                      </td>
                      <td>
                        <Badge tone={KIND[d.source_kind].tone}>{KIND[d.source_kind].short}</Badge>
                      </td>
                      <td>{d.location ?? "—"}</td>
                      <td>
                        <ReadinessChip readiness={d.readiness} title={deviceReadinessDetail(d)} />
                        {d.logged_in_user && (
                          <div className="app-card-meta app-mono mt-1">{d.logged_in_user}</div>
                        )}
                      </td>
                      <td>
                        {d.has_password ? (
                          <span
                            className="text-xs text-slate-600"
                            title={`сгенерирован ${relTime(d.password_rotated_at)}; применяется при раскатке`}
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
                                title="Развернуть тихо через InfraScope"
                                disabled={deployMut.isPending}
                                onClick={() => deployMut.mutate(d.id)}
                              >
                                <Rocket className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                variant="secondary"
                                size="sm"
                                className="!px-2"
                                title="Сгенерировать новый пароль"
                                onClick={() => rotateMut.mutate(d.id)}
                              >
                                <KeyRound className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                variant="secondary"
                                size="sm"
                                className="!px-2"
                                title="Протолкнуть в книгу адресов"
                                disabled={consoleDown || !d.rustdesk_id}
                                onClick={() => abMut.mutate({ device_ids: [d.id] })}
                              >
                                <BookUser className="h-3.5 w-3.5" />
                              </Button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!isLoading && rows.length === 0 && (
                    <tr>
                      <td colSpan={8} className="py-10 text-center text-gray-400">
                        Нет устройств. Нажмите «Синхронизировать».
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <p className="px-1 text-xs text-gray-400">
            «Скрытый» режим убирает трей, ярлыки и пункты настроек, но не прячет системный
            индикатор активной сессии RustDesk — этого клиент с открытым кодом не умеет.
          </p>
        </div>
      )}

      {tab === "accounts" && <ConsoleAccountsPanel isSuperuser={isSuperuser} />}

      {tab === "connections" && (
        <div className="app-panel overflow-hidden">
          <div className="border-b border-slate-200 bg-slate-50/70 px-4 py-3 text-sm font-semibold text-slate-700">
            Последние подключения
          </div>
          {consoleDown ? (
            <div className="px-4 py-6 text-sm text-gray-500">
              Консоль недоступна. Укажите <code className="app-mono">RUSTDESK_API_TOKEN</code> в{" "}
              <code className="app-mono">.env</code> сервера (Settings → API tokens в веб-консоли RustDesk).
            </div>
          ) : (
            <div className="overflow-x-auto app-compact-scroll">
              <table className="app-table min-w-full">
                <thead>
                  <tr>
                    <th>Откуда</th>
                    <th>Куда</th>
                    <th>IP</th>
                    <th>Действие</th>
                    <th>Начало</th>
                    <th>Конец</th>
                  </tr>
                </thead>
                <tbody>
                  {(consoleConns.data ?? []).map((c, i) => (
                    <tr key={c.id ?? i}>
                      <td className="app-mono text-xs">{c.from_name || c.from_peer || "—"}</td>
                      <td className="app-mono text-xs">{c.peer_id || "—"}</td>
                      <td className="app-mono text-xs text-gray-400">{c.ip || "—"}</td>
                      <td className="text-xs text-gray-500">{c.action || "—"}</td>
                      <td className="text-xs text-gray-400">{c.created_at?.slice(0, 16) ?? "—"}</td>
                      <td className="text-xs text-gray-400">{c.close_time?.slice(0, 16) ?? "—"}</td>
                    </tr>
                  ))}
                  {(consoleConns.data ?? []).length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-10 text-center text-gray-400">
                        Пока пусто.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <DeployCommandModal open={deployModalOpen} onClose={() => setDeployModalOpen(false)} />
    </div>
  );
}
