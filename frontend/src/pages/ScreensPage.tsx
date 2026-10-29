import { useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Radar, RefreshCw, Search, Tv } from "lucide-react";
import { useAuth } from "../auth";
import { discoverComputers, getCashRegisters, getRemoteDevices, type RemoteDevice } from "../client";
import RemoteAccessButtons from "../components/RemoteAccessButtons";
import { filterScreenZones, groupScreens, isActiveScreen, isListedScreen, screenState, type ScreenState } from "../lib/screens";
import { relTime } from "../lib/relTime";
import { showToast } from "../lib/toastBus";
import { apiErrorMessage } from "../lib/apiError";

const DOT: Record<ScreenState, string> = {
  online: "bg-teal-500",
  reachable: "bg-sky-400",
  offline: "bg-slate-400",
  unknown: "border border-dashed border-slate-400 bg-transparent",
};

const STATE_TEXT: Record<ScreenState, string> = {
  online: "на связи",
  reachable: "машина включена, RustDesk не подключён",
  offline: "не в сети",
  unknown: "нет данных",
};

function Stat({ label, value, detail }: { label: string; value: number; detail?: string }) {
  return (
    <div className="app-panel p-4">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-slate-800">{value}</p>
      {detail && <p className="mt-1 text-xs text-slate-500">{detail}</p>}
    </div>
  );
}

function ScreenRow({ screen, canManage }: { screen: RemoteDevice; canManage: boolean }) {
  const state = screenState(screen);
  return (
    <li className="flex flex-col gap-2 py-2.5 sm:flex-row sm:items-center sm:justify-between" data-testid={`screen-${screen.hostname}`}>
      <div className="flex min-w-0 items-center gap-3">
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT[state]}`} aria-hidden="true" />
        <div className="min-w-0">
          <p className="truncate font-mono text-sm font-medium text-slate-900">
            {screen.hostname}
          </p>
          <p className="text-xs text-slate-500">
            {STATE_TEXT[state]}
            {screen.logged_in_user ? ` · пользователь ${screen.logged_in_user}` : ""}
            {state === "online" ? "" : screen.last_seen_at ? ` · был в консоли ${relTime(screen.last_seen_at)}` : ""}
          </p>
        </div>
      </div>
      <RemoteAccessButtons hostname={screen.hostname} device={screen} canManage={canManage} compact />
    </li>
  );
}

/** The store display machines (TV boxes) on their own page: which are up, and a connect button each.
 *  They used to be mixed into the Remote Access device list among ~200 tills and computers. */
export default function ScreensPage() {
  const { user } = useAuth();
  const isSuperuser = Boolean(user?.is_superuser);
  const [query, setQuery] = useState("");
  const [onlyActive, setOnlyActive] = useState(true);

  const queryClient = useQueryClient();
  const devices = useQuery({
    queryKey: ["remote-devices", "screens"],
    // with the entries out of management: a screen that is up still belongs here (see isListedScreen)
    queryFn: () => getRemoteDevices({ include_unmanaged: true }),
    placeholderData: keepPreviousData,
    refetchInterval: 20_000,
  });
  const cash = useQuery({ queryKey: ["cash-registers", undefined], queryFn: () => getCashRegisters(), staleTime: 60_000, retry: false });
  const discover = useMutation({
    mutationFn: discoverComputers,
    onSuccess: (result) => {
      showToast(
        result.added.length
          ? `Найдено в сети и добавлено: ${result.added.join(", ")}`
          : result.seen
            ? `Новых экранов в сети нет (в DNS ${result.matched} экранов, все уже в списке)`
            : `DNS-зона ${result.zone || "(не задана)"} не прочиталась — новых экранов не найти`,
        result.seen ? "success" : "error",
      );
      queryClient.invalidateQueries({ queryKey: ["remote-devices"] });
    },
    onError: (error) => showToast(apiErrorMessage(error, "Не удалось поискать экраны в сети"), "error"),
  });

  const all = useMemo(() => (devices.data?.data ?? []).filter(isListedScreen), [devices.data]);
  const active = all.filter(isActiveScreen);
  const zones = useMemo(() => {
    const shown = all.filter((s) => !onlyActive || isActiveScreen(s));
    return filterScreenZones(groupScreens(shown, cash.data?.data ?? []), query);
  }, [all, cash.data, onlyActive, query]);

  const hidden = all.length - all.filter((s) => !onlyActive || isActiveScreen(s)).length;

  return (
    <div className="space-y-5">
      <section className="grid grid-cols-3 gap-2 sm:gap-3" aria-label="Статистика экранов">
        <Stat label="Экранов" value={all.length} />
        <Stat label="Активных" value={active.length} detail={all.length ? `${all.length - active.length} не в сети` : undefined} />
        <Stat label="На связи в RustDesk" value={all.filter((s) => screenState(s) === "online").length} detail="к ним можно подключиться" />
      </section>

      <div className="app-panel flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <label className="relative sm:w-72">
          <span className="sr-only">Найти экран или магазин</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Экран или магазин" className="app-input w-full py-2 pl-9 pr-3 text-sm" />
        </label>
        <div className="flex flex-wrap items-center gap-4">
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={onlyActive} onChange={(e) => setOnlyActive(e.target.checked)} />
            Только активные
            {onlyActive && hidden > 0 && <span className="text-xs text-slate-400">(скрыто {hidden})</span>}
          </label>
          {isSuperuser && (
            <button
              type="button"
              onClick={() => discover.mutate()}
              disabled={discover.isPending}
              className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm disabled:opacity-50"
              title="Добавить TV-машины, которые есть в DNS домена, но ещё не в списке (это же делается автоматически раз в час)"
            >
              <Radar className={`h-4 w-4 ${discover.isPending ? "animate-pulse" : ""}`} />
              Найти в сети
            </button>
          )}
          <button type="button" onClick={() => void devices.refetch()} className="app-btn-secondary inline-flex items-center gap-2 px-3 py-2 text-sm">
            <RefreshCw className={`h-4 w-4 ${devices.isFetching ? "animate-spin" : ""}`} />
            Обновить
          </button>
        </div>
      </div>

      {devices.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="app-skeleton h-28" />)}</div>
      ) : devices.isError ? (
        <div className="app-panel p-8 text-center text-sm text-slate-600">Не удалось загрузить экраны. Попробуйте обновить позже.</div>
      ) : zones.length === 0 ? (
        <div className="app-panel flex flex-col items-center gap-2 p-10 text-center text-sm text-slate-500">
          <Tv className="h-8 w-8 text-slate-300" />
          {all.length === 0
            ? "Экранов нет: в удалённом доступе нет устройств с TV в имени. «Найти в сети» поищет их в DNS домена."
            : onlyActive && !query
              ? "Активных экранов нет. Снимите «Только активные», чтобы увидеть остальные."
              : "По этому запросу экранов нет."}
        </div>
      ) : (
        zones.map((zone) => (
          <section key={zone.key} data-testid={`zone-${zone.key}`}>
            <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h3 className="text-sm font-semibold text-slate-800">{zone.label}</h3>
              <span className="text-xs text-slate-500">{zone.total} экранов · {zone.active} активны</span>
            </div>
            <div className="grid gap-3 lg:grid-cols-2 min-[1920px]:grid-cols-3">
              {zone.stores.map((store) => (
                <div key={store.key} data-testid={`store-${store.key}`} className="app-panel p-4">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <h4 className="truncate text-sm font-medium text-slate-800" title={store.title}>{store.title}</h4>
                    <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold tabular-nums text-slate-700">
                      {store.screens.filter(isActiveScreen).length}/{store.screens.length}
                    </span>
                  </div>
                  <ul className="divide-y divide-[var(--app-panel-border)]">
                    {store.screens.map((screen) => <ScreenRow key={screen.id} screen={screen} canManage={isSuperuser} />)}
                  </ul>
                </div>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}
