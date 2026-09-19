import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
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
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { useAuth } from "../auth";
import {
  deleteRemoteDevice,
  ensureRustDeskDevice,
  getAddressBookStatus,
  getConsoleConnections,
  getRemoteDevices,
  requestDeploy,
  rotateRemotePassword,
  rustdeskLink,
  setDeviceProfile,
  syncAddressBook,
  syncRemoteAccess,
  updateRemoteDevice,
  type DeployProfile,
  type Readiness,
  type RemoteDevice,
  type SourceKind,
} from "../client";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { showToast } from "../lib/toastBus";
import { relTime } from "../lib/relTime";
import { Button } from "../components/ui/Button";
import { AppLockerMismatchBadge, READINESS_META, ReadinessChip, deviceReadinessDetail } from "../components/RemoteAccessStatus";
import DeployCommandModal from "../components/DeployCommandModal";
import ConsoleAccountsPanel from "../components/ConsoleAccountsPanel";
import UnlistedConsolePeersPanel from "../components/UnlistedConsolePeersPanel";
import { isScreen } from "../lib/screens";

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

/** The rollout button reapplies the *entire* current config on every run
 *  (id, password, hidden/block_outgoing/unattended) - it just reads better as
 *  "Передеплоить" once the machine has actually been configured before. */
function isRedeploy(d: RemoteDevice): boolean {
  return d.readiness === "ready" || d.readiness === "installed_offline" || d.readiness === "stale";
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
  const [typeTag, setTypeTag] = useState("");
  const [showScreens, setShowScreens] = useState(false);
  const [statusFilter, setStatusFilter] = useState<"" | Readiness>("");
  const [deployModalOpen, setDeployModalOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [addHostname, setAddHostname] = useState("");

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
  const abStatus = useQuery({
    queryKey: ["rd-console", "address-book-status"],
    queryFn: getAddressBookStatus,
    retry: false,
    refetchInterval: 30000,
    enabled: tab === "devices" && !consoleDown,
  });
  // 0 almost always - the background sync (every 2 min) both detects and
  // fixes this on its own; a sustained nonzero reading is the one worth a look
  const abMissing = abStatus.data?.missing ?? 0;

  const allRows = useMemo(() => data?.data ?? [], [data]);
  // the store TVs have their own tab ("Экраны"); they stay out of this list unless asked for
  const screenCount = useMemo(() => allRows.filter(isScreen).length, [allRows]);
  const rows = useMemo(() => (showScreens ? allRows : allRows.filter((r) => !isScreen(r))), [allRows, showScreens]);
  const locations = useMemo(
    () => Array.from(new Set(rows.map((r) => r.location).filter((x): x is string => !!x))).sort(),
    [rows],
  );
  // role token off the hostname (KKM/MGR/TV/MUZ/SRV/...) - see service.hostname_type_tag.
  // No backend filter for this yet, so it narrows client-side like the other dropdowns.
  const typeTags = useMemo(
    () => Array.from(new Set(rows.map((r) => r.type_tag).filter((x): x is string => !!x))).sort(),
    [rows],
  );
  const visibleRows = useMemo(
    () =>
      rows.filter((r) => (!typeTag || r.type_tag === typeTag) && (!statusFilter || r.readiness === statusFilter)),
    [rows, typeTag, statusFilter],
  );
  // only the statuses that occur, with how many - an empty option is noise
  const statusCounts = useMemo(() => {
    const counts = new Map<Readiness, number>();
    for (const r of rows) counts.set(r.readiness, (counts.get(r.readiness) ?? 0) + 1);
    return counts;
  }, [rows]);
  const summary = useMemo(
    () => ({
      total: visibleRows.length,
      ready: visibleRows.filter((r) => r.readiness === "ready").length,
      inBook: visibleRows.filter((r) => r.in_address_book).length,
      noId: visibleRows.filter((r) => !r.rustdesk_id).length,
      applockerMismatch: visibleRows.filter((r) => r.applocker_mismatch).length,
    }),
    [visibleRows],
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
  const profileMut = useMutation({
    mutationFn: ({ id, profile }: { id: string; profile: DeployProfile }) => setDeviceProfile(id, profile),
    onSuccess: (dev) => {
      showToast(
        dev.deploy_profile === "admin"
          ? `${dev.hostname}: профиль «Админ» — полный доступ, без ограничений`
          : `${dev.hostname}: профиль «Клиент» — заблокировано для пользователя`,
        "success",
      );
      invalidate();
    },
    onError: () => showToast("Не удалось сменить профиль", "error"),
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
    const scope =
      [kind ? KIND[kind].label : null, location, typeTag].filter(Boolean).join(" / ") || "все управляемые";
    if (!window.confirm(`Протолкнуть в общую книгу адресов: ${scope}?`)) return;
    // the console has no type_tag filter of its own - when one is picked, push
    // exactly the rows the table is showing instead (default page size already
    // covers the whole fleet, so this isn't a narrower set than the server would give)
    abMut.mutate(
      typeTag || statusFilter
        ? { device_ids: visibleRows.map((r) => r.id) }
        : {
            ...(location ? { location } : {}),
            ...(kind ? { source_kind: kind } : {}),
          },
    );
  };

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteRemoteDevice(id),
    onSuccess: (r) => {
      showToast(r.message, "success");
      invalidate();
    },
    onError: () => showToast("Не удалось удалить устройство", "error"),
  });

  const addMut = useMutation({
    mutationFn: (hostname: string) => ensureRustDeskDevice({ hostname }),
    onSuccess: (dev) => {
      showToast(`${dev.hostname}: добавлен в удалённый доступ`, "success");
      invalidate();
      setAddOpen(false);
      setAddHostname("");
    },
    onError: () => showToast("Не удалось добавить устройство", "error"),
  });

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

          {summary.applockerMismatch > 0 && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
              <b>{summary.applockerMismatch}</b>{" "}
              {summary.applockerMismatch === 1 ? "устройство" : "устройств"} на Windows Home — AppLocker
              там недоступен, запрет ручного запуска клиента не применился (см. значок «Home» в строке).
            </div>
          )}

          {abMissing > 0 && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
              <b>{abMissing}</b> {abMissing === 1 ? "устройство отмечено" : "устройств отмечены"} как «в
              книге адресов», но в консоли этой записи сейчас нет — фон подтянет само в течение пары минут;
              если висит дольше, нажмите «В книгу адресов».
            </div>
          )}

          <UnlistedConsolePeersPanel isSuperuser={isSuperuser} />

          {screenCount > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-600">
              <span>
                Телевизоры ({screenCount}) вынесены во вкладку{" "}
                <Link to="/screens" className="font-medium text-[var(--brand)] hover:underline">«Экраны»</Link>.
              </span>
              <label className="inline-flex cursor-pointer items-center gap-2">
                <input type="checkbox" checked={showScreens} onChange={(e) => setShowScreens(e.target.checked)} />
                Показывать и здесь
              </label>
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
              <select
                className="app-input px-3 py-2 text-sm text-slate-700"
                value={typeTag}
                onChange={(e) => setTypeTag(e.target.value)}
                title="Тип по имени хоста: VNA-KKM-1506 -> KKM"
              >
                <option value="">Все типы</option>
                {typeTags.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              <select
                className="app-input px-3 py-2 text-sm text-slate-700"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as "" | Readiness)}
                aria-label="Статус"
              >
                <option value="">Все статусы</option>
                {(Object.keys(READINESS_META) as Readiness[])
                  .filter((k) => statusCounts.has(k))
                  .map((k) => (
                    <option key={k} value={k}>
                      {READINESS_META[k].label} ({statusCounts.get(k)})
                    </option>
                  ))}
              </select>
              <div className="ml-auto flex gap-2">
                <Button variant="secondary" onClick={() => syncMut.mutate()} disabled={syncMut.isPending}>
                  <RefreshCw className={`mr-1 h-4 w-4 ${syncMut.isPending ? "animate-spin" : ""}`} />
                  Синхронизировать
                </Button>
                {isSuperuser && (
                  <Button variant="secondary" onClick={() => setAddOpen(true)}>
                    <Plus className="mr-1 h-4 w-4" />
                    Добавить устройство
                  </Button>
                )}
                {isSuperuser && (
                  <Button variant="secondary" onClick={() => setDeployModalOpen(true)}>
                    <Terminal className="mr-1 h-4 w-4" />
                    Команда развёртывания
                  </Button>
                )}
                {isSuperuser && (
                  <Button onClick={bulkAb} disabled={abMut.isPending || consoleDown}>
                    <BookUser className="mr-1 h-4 w-4" />
                    В книгу адресов
                    {location || kind || typeTag
                      ? ` · ${[kind ? KIND[kind].label : null, location, typeTag].filter(Boolean).join(" / ")}`
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
                    <th>Тип</th>
                    <th>Точка</th>
                    <th>Готовность</th>
                    <th>Пароль</th>
                    <th>Профиль / защита</th>
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
                  {visibleRows.map((d) => (
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
                      <td>
                        {d.type_tag ? <Badge>{d.type_tag}</Badge> : <span className="text-gray-400">—</span>}
                      </td>
                      <td>{d.location ?? "—"}</td>
                      <td>
                        <div className="flex flex-wrap items-center gap-1">
                          <ReadinessChip readiness={d.readiness} title={deviceReadinessDetail(d)} />
                          <AppLockerMismatchBadge device={d} compact />
                        </div>
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
                        <select
                          className="app-input px-2 py-1 text-xs"
                          value={d.deploy_profile}
                          disabled={!isSuperuser || profileMut.isPending}
                          title={
                            d.deploy_profile === "admin"
                              ? "Полный доступ: видимый клиент, можно подключаться самому"
                              : "Заблокировано для пользователя: скрыт, AppLocker не даёт запустить самому"
                          }
                          onChange={(e) =>
                            profileMut.mutate({ id: d.id, profile: e.target.value as DeployProfile })
                          }
                        >
                          <option value="client">Клиент</option>
                          <option value="admin">Админ</option>
                        </select>
                        <div className="mt-1 flex gap-1">
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
                                title={
                                  isRedeploy(d)
                                    ? "Передеплоить: заново применить текущие ID, пароль и настройки скрытности/блокировки"
                                    : "Развернуть тихо через InfraScope"
                                }
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
                              <Button
                                variant="secondary"
                                size="sm"
                                className="!px-2 !text-rose-600 hover:!bg-rose-50"
                                title="Удалить из удалённого доступа"
                                disabled={deleteMut.isPending}
                                onClick={() => {
                                  if (window.confirm(`Удалить ${d.hostname} из удалённого доступа?`)) {
                                    deleteMut.mutate(d.id);
                                  }
                                }}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!isLoading && visibleRows.length === 0 && (
                    <tr>
                      <td colSpan={9} className="py-10 text-center text-gray-400">
                        {rows.length === 0
                          ? "Нет устройств. Нажмите «Синхронизировать»."
                          : "Ничего не подходит под выбранный тип."}
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

      {addOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
          <div className="app-panel w-full max-w-md space-y-4 p-5">
            <div className="flex items-start justify-between">
              <h2 className="text-base font-semibold text-slate-900">Добавить устройство</h2>
              <button onClick={() => setAddOpen(false)} className="text-slate-400 hover:text-slate-700">
                <X className="h-5 w-5" />
              </button>
            </div>
            <p className="text-xs text-slate-500">
              Заводит устройство под удалённый доступ по имени хоста — привязывается к инвентарю,
              если хост там уже есть, но работает и для хоста, которого там нет. ID и пароль
              InfraScope сгенерирует сам; поменять их можно после, кнопкой «Настроить». В книгу
              адресов новое устройство попадёт при следующем «В книгу адресов».
            </p>
            <label className="block text-sm">
              <span className="mb-1 block text-slate-600">Hostname</span>
              <input
                autoFocus
                className="app-input w-full px-3 py-2 text-sm"
                value={addHostname}
                onChange={(e) => setAddHostname(e.target.value)}
                placeholder="VNA-KKM-1507"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && addHostname.trim()) addMut.mutate(addHostname.trim());
                }}
              />
            </label>
            <div className="flex justify-end gap-2">
              <button onClick={() => setAddOpen(false)} className="app-btn-secondary px-4 py-2 text-sm">
                Отмена
              </button>
              <button
                onClick={() => addMut.mutate(addHostname.trim())}
                disabled={addMut.isPending || !addHostname.trim()}
                className="app-btn-primary px-4 py-2 text-sm disabled:opacity-50"
              >
                Добавить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
