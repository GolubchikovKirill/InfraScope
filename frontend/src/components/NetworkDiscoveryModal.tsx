import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRightLeft, CheckCircle2, Loader2, Plus, Search, Wifi } from "lucide-react";
import {
  addDiscoveredIconbit,
  addDiscoveredSwitch,
  getIconbitDiscoveryResults,
  getScannerSettings,
  getSwitchDiscoveryResults,
  startIconbitDiscoveryScan,
  startSwitchDiscoveryScan,
  updateDiscoveredIconbitIp,
  updateDiscoveredSwitchIp,
  type DiscoveredNetworkDevice,
} from "../client";

type DiscoveryKind = "iconbit" | "switch";

interface Props {
  kind: DiscoveryKind;
  onClose: () => void;
}

export default function NetworkDiscoveryModal({ kind, onClose }: Props) {
  const queryClient = useQueryClient();
  const [subnet, setSubnet] = useState("");
  const [ports, setPorts] = useState(kind === "iconbit" ? "8081,80,443" : "22,80,443");
  const [polling, setPolling] = useState(false);

  const { data: settingsData } = useQuery({
    queryKey: ["scanner-settings"],
    queryFn: getScannerSettings,
  });

  useEffect(() => {
    if (settingsData?.subnet) setSubnet(settingsData.subnet);
  }, [settingsData]);

  const isIconbit = kind === "iconbit";
  const queryKey = isIconbit ? ["discover-iconbit-results"] : ["discover-switch-results"];
  const queryFn = isIconbit ? getIconbitDiscoveryResults : getSwitchDiscoveryResults;

  const { data: resultsData, refetch } = useQuery({
    queryKey,
    queryFn,
    refetchInterval: polling ? 2000 : false,
  });

  const progress = resultsData?.progress ?? { status: "idle", scanned: 0, total: 0, found: 0, message: null };
  const devices = resultsData?.devices ?? [];

  useEffect(() => {
    if (progress.status === "running" && !polling) setPolling(true);
    if (progress.status !== "running" && polling) setPolling(false);
  }, [progress.status, polling]);

  const startMut = useMutation({
    mutationFn: async () => {
      const res = isIconbit ? await startIconbitDiscoveryScan(subnet, ports) : await startSwitchDiscoveryScan(subnet, ports);
      return res;
    },
    onSuccess: () => {
      setPolling(true);
      refetch();
    },
  });

  const addMut = useMutation({
    mutationFn: async (d: DiscoveredNetworkDevice) => {
      if (isIconbit) {
        const res = await addDiscoveredIconbit({
          ip_address: d.ip,
          name: d.hostname || `Iconbit ${d.ip}`,
          model: d.model_info || "Iconbit",
          mac_address: d.mac ?? undefined,
        });
        return res;
      }
      const res = await addDiscoveredSwitch({
        ip_address: d.ip,
        name: d.hostname || `Switch ${d.ip}`,
        hostname: d.hostname ?? undefined,
        vendor: d.vendor ?? "generic",
      });
      return res;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: isIconbit ? ["media-players"] : ["switches"] });
      refetch();
    },
  });

  const updateIpMut = useMutation({
    mutationFn: async (d: DiscoveredNetworkDevice) => {
      if (!d.known_device_id) throw new Error("known_device_id is required");
      if (isIconbit) {
        const res = await updateDiscoveredIconbitIp(d.known_device_id, d.ip, d.mac ?? undefined);
        return res;
      }
      const res = await updateDiscoveredSwitchIp(d.known_device_id, d.ip);
      return res;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: isIconbit ? ["media-players"] : ["switches"] });
      refetch();
    },
  });

  const isScanning = progress.status === "running" || startMut.isPending;
  const pct = progress.total > 0 ? Math.round((progress.scanned / progress.total) * 100) : 0;
  const title = isIconbit ? "Поиск Iconbit в сети" : "Поиск свитчей в сети";

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="app-panel w-full max-w-6xl max-h-[90vh] overflow-hidden border-slate-200/70 shadow-2xl">
        <div className="p-4 border-b border-slate-200 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Wifi className="h-5 w-5 text-rose-600" />
            <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
          </div>
          <button onClick={onClose} className="app-btn-secondary px-3 py-2 text-sm">Закрыть</button>
        </div>
        <div className="p-4 border-b border-slate-200">
          <div className="flex flex-col sm:flex-row gap-3">
            <input
              value={subnet}
              onChange={(e) => setSubnet(e.target.value)}
              placeholder="10.10.98.0/24, 10.10.99.0/24"
              className="app-input flex-1 px-3 py-2 text-sm"
            />
            <input
              value={ports}
              onChange={(e) => setPorts(e.target.value)}
              placeholder={isIconbit ? "8081,80,443" : "22,80,443"}
              className="app-input w-full sm:w-56 px-3 py-2 text-sm"
            />
            <button
              onClick={() => startMut.mutate()}
              disabled={isScanning || !subnet}
              className="app-btn-primary inline-flex items-center justify-center gap-2 px-4 py-2 text-sm disabled:opacity-50"
            >
              {isScanning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {isScanning ? "Сканирование..." : "Сканировать"}
            </button>
          </div>
          {(isScanning || progress.status === "done") && (
            <div className="mt-3">
              <div className="flex justify-between text-xs text-slate-500">
                <span>{progress.message || `Сканирование: ${progress.scanned}/${progress.total}`}</span>
                <span>{pct}%</span>
              </div>
              <div className="w-full bg-slate-200 rounded-full h-2 mt-1">
                <div className={`h-2 rounded-full ${progress.status === "done" ? "bg-emerald-500" : "bg-rose-500"}`} style={{ width: `${pct}%` }} />
              </div>
            </div>
          )}
          {progress.status === "error" && progress.message && (
            <div className="mt-3 flex items-center gap-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              {progress.message}
            </div>
          )}
        </div>
        <div className="overflow-auto max-h-[60vh] app-compact-scroll">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 sticky top-0 z-10">
              <tr className="text-left text-slate-600">
                <th className="px-3 py-2">IP</th>
                <th className="px-3 py-2">MAC</th>
                <th className="px-3 py-2">Порты</th>
                <th className="px-3 py-2">Hostname</th>
                <th className="px-3 py-2">Модель</th>
                <th className="px-3 py-2">Vendor</th>
                <th className="px-3 py-2">Статус</th>
                <th className="px-3 py-2">Действия</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => (
                <tr key={d.ip} className="border-t border-slate-100 hover:bg-slate-50/60">
                  <td className="px-3 py-2 font-mono">{d.ip}</td>
                  <td className="px-3 py-2 font-mono">{d.mac || "—"}</td>
                  <td className="px-3 py-2">{d.open_ports.join(", ")}</td>
                  <td className="px-3 py-2">{d.hostname || "—"}</td>
                  <td className="px-3 py-2">{d.model_info || "—"}</td>
                  <td className="px-3 py-2">{d.vendor || "—"}</td>
                  <td className="px-3 py-2">
                    {d.ip_changed ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-700 px-2 py-0.5">
                        <ArrowRightLeft className="h-3 w-3" /> IP сменился
                      </span>
                    ) : d.is_known ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 text-emerald-700 px-2 py-0.5">
                        <CheckCircle2 className="h-3 w-3" /> Известен
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded-full bg-rose-100 text-rose-700 px-2 py-0.5">Новый</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {d.ip_changed && d.known_device_id ? (
                      <button
                        onClick={() => updateIpMut.mutate(d)}
                        disabled={updateIpMut.isPending}
                        className="app-btn-secondary inline-flex items-center gap-1 px-2 py-1 text-xs"
                      >
                        <ArrowRightLeft className="h-3 w-3" /> Обновить IP
                      </button>
                    ) : !d.is_known ? (
                      <button
                        onClick={() => addMut.mutate(d)}
                        disabled={addMut.isPending}
                        className="app-btn-secondary inline-flex items-center gap-1 px-2 py-1 text-xs"
                      >
                        <Plus className="h-3 w-3" /> Добавить
                      </button>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {progress.status === "done" && devices.length === 0 && (
            <div className="p-8 text-sm text-slate-500 text-center">Устройства не найдены</div>
          )}
        </div>
      </div>
    </div>
  );
}
