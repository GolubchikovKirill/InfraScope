import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, EyeOff, PlusCircle } from "lucide-react";
import {
  adoptConsolePeer,
  dismissConsolePeer,
  getUnlistedConsolePeers,
  type DeployProfile,
  type UnlistedPeer,
} from "../client";
import { relTime } from "../lib/relTime";
import { showToast } from "../lib/toastBus";

const PROFILE_LABEL: Record<DeployProfile, string> = {
  admin: "Рабочее место инженера",
  client: "Клиент (киоск)",
};

/** Machines the RustDesk console knows but the device list does not.
 *
 *  The list is built from InfraScope's inventory, and the console peer sync
 *  deliberately never creates a device (it once turned someone's personal laptop
 *  into a managed one). So the IT department's own workstations, which are not in
 *  the inventory, could not appear at all. This panel is the explicit half: the
 *  console's view, with a person deciding per machine - take it under management
 *  or hide it for good. Nothing is applied to the machine either way. */
export default function UnlistedConsolePeersPanel({ isSuperuser }: { isSuperuser: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(true);
  const [profiles, setProfiles] = useState<Record<string, DeployProfile>>({});

  const { data } = useQuery({
    queryKey: ["remote-access", "unlisted-peers"],
    queryFn: getUnlistedConsolePeers,
    enabled: isSuperuser,
    retry: false,
    refetchInterval: 60000,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["remote-access", "unlisted-peers"] });
    qc.invalidateQueries({ queryKey: ["remote-devices"] });
  };

  const adoptMut = useMutation({
    mutationFn: (p: { hostname: string; profile: DeployProfile }) => adoptConsolePeer(p),
    onSuccess: (dev) => {
      showToast(`${dev.hostname}: взято в управление`, "success");
      refresh();
    },
    onError: () => showToast("Не удалось взять машину в управление", "error"),
  });

  const dismissMut = useMutation({
    mutationFn: (hostname: string) => dismissConsolePeer(hostname),
    onSuccess: (r) => {
      showToast(r.message, "success");
      refresh();
    },
    onError: () => showToast("Не удалось скрыть машину", "error"),
  });

  if (!isSuperuser || !data || !data.console_reachable || data.count === 0) return null;

  const profileOf = (p: UnlistedPeer): DeployProfile => profiles[p.hostname] ?? p.suggested_profile;
  const busy = adoptMut.isPending || dismissMut.isPending;

  return (
    <div className="app-panel overflow-hidden" data-testid="unlisted-peers">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 border-b border-slate-200 bg-slate-50/70 px-4 py-3 text-left"
        aria-expanded={open}
      >
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <span className="text-sm font-semibold text-slate-800">
          В консоли RustDesk есть машины, которых нет в списке
        </span>
        <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-800">{data.count}</span>
      </button>

      {open && (
        <div className="space-y-3 p-4">
          <p className="text-sm text-slate-600">
            Список устройств строится из инвентаря InfraScope, поэтому рабочие места вне инвентаря (например,
            компьютеры ИТ-отдела) сами сюда не попадают. Здесь они видны такими, какими их знает консоль.
            «Взять в управление» только заводит запись и пароль; на самой машине ничего не меняется, пока там не
            запустят раскатку. «Скрыть» убирает из предложений навсегда (личные и тестовые машины).
          </p>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-2 py-1.5">Машина</th>
                  <th className="px-2 py-1.5">Система</th>
                  <th className="px-2 py-1.5">Пользователь</th>
                  <th className="px-2 py-1.5">Был в сети</th>
                  <th className="px-2 py-1.5">Профиль</th>
                  <th className="px-2 py-1.5" />
                </tr>
              </thead>
              <tbody>
                {data.data.map((p) => (
                  <tr key={p.hostname} className="border-t border-slate-100">
                    <td className="px-2 py-2 font-medium text-slate-900">
                      <span
                        className={`mr-2 inline-block h-2 w-2 rounded-full ${p.online ? "bg-emerald-500" : "bg-slate-300"}`}
                        title={p.online ? "онлайн" : "не в сети"}
                      />
                      <span className="app-mono">{p.hostname}</span>
                    </td>
                    <td className="px-2 py-2 text-slate-600">
                      {[p.os, p.version && `RustDesk ${p.version}`].filter(Boolean).join(" · ") || "—"}
                    </td>
                    <td className="px-2 py-2 text-slate-600">{p.username || "—"}</td>
                    <td className="px-2 py-2 text-slate-600">{p.online ? "сейчас" : relTime(p.last_online)}</td>
                    <td className="px-2 py-2">
                      <select
                        className="app-input px-2 py-1 text-sm"
                        aria-label={`Профиль для ${p.hostname}`}
                        value={profileOf(p)}
                        onChange={(e) =>
                          setProfiles((prev) => ({ ...prev, [p.hostname]: e.target.value as DeployProfile }))
                        }
                        disabled={busy}
                      >
                        {(Object.keys(PROFILE_LABEL) as DeployProfile[]).map((k) => (
                          <option key={k} value={k}>
                            {PROFILE_LABEL[k]}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 text-right">
                      <button
                        type="button"
                        className="app-btn-primary inline-flex items-center gap-1.5 px-3 py-1.5 text-sm disabled:opacity-50"
                        disabled={busy}
                        onClick={() => adoptMut.mutate({ hostname: p.hostname, profile: profileOf(p) })}
                      >
                        <PlusCircle className="h-4 w-4" /> Взять в управление
                      </button>
                      <button
                        type="button"
                        className="ml-2 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-50"
                        disabled={busy}
                        onClick={() => dismissMut.mutate(p.hostname)}
                        title="Больше не предлагать эту машину"
                      >
                        <EyeOff className="h-4 w-4" /> Скрыть
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.nameless_peers > 0 && (
            <p className="text-xs text-slate-500">
              Ещё {data.nameless_peers} {data.nameless_peers === 1 ? "запись" : "записей"} в консоли без имени
              машины (клиент так и не сообщил hostname): назвать их нельзя, поэтому здесь они не показаны.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
