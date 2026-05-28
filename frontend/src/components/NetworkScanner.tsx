import { useState, useEffect, useRef, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Wifi,
  Search,
  Plus,
  ArrowRightLeft,
  CheckCircle2,
  AlertTriangle,
  Monitor,
  Loader2,
} from "lucide-react";
import {
  startScan,
  getScanResults,
  getScanStatus,
  getScannerSettings,
  addDiscoveredPrinter,
  updatePrinterIp,
  type DiscoveredDevice,
  type ScanProgress,
} from "../client";
import { useAuth } from "../auth";

export default function NetworkScanner() {
  const { user } = useAuth();
  const isSuperuser = user?.is_superuser ?? false;
  const queryClient = useQueryClient();

  const [subnet, setSubnet] = useState("");
  const [ports, setPorts] = useState("9100,631,80,443");
  const [polling, setPolling] = useState(false);

  const { data: settingsData } = useQuery({
    queryKey: ["scanner-settings"],
    queryFn: getScannerSettings,
  });

  useEffect(() => {
    if (settingsData) {
      if (settingsData.subnet) setSubnet(settingsData.subnet);
      if (settingsData.ports) setPorts(settingsData.ports);
    }
  }, [settingsData]);

  const { data: resultsData, refetch: refetchResults } = useQuery({
    queryKey: ["scan-results"],
    queryFn: getScanResults,
    refetchInterval: polling ? 2000 : false,
  });

  const progress = resultsData?.progress ?? {
    status: "idle" as const,
    scanned: 0,
    total: 0,
    found: 0,
    message: null,
  };
  const devices = resultsData?.devices ?? [];

  // Auto-resume polling when component mounts and scan is in progress
  useEffect(() => {
    if (progress.status === "running" && !polling) {
      setPolling(true);
    }
    if (progress.status === "done" || progress.status === "error" || progress.status === "idle") {
      if (polling) setPolling(false);
    }
  }, [progress.status, polling]);

  const scanMut = useMutation({
    mutationFn: () => startScan(subnet, ports),
    onSuccess: () => {
      setPolling(true);
      refetchResults();
    },
  });

  const addMut = useMutation({
    mutationFn: addDiscoveredPrinter,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["printers"] });
      refetchResults();
    },
  });

  const updateIpMut = useMutation({
    mutationFn: ({ id, ip, mac }: { id: string; ip: string; mac?: string }) =>
      updatePrinterIp(id, ip, mac ?? undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["printers"] });
      refetchResults();
    },
  });

  const isScanning = progress.status === "running" || scanMut.isPending;
  const pct = progress.total > 0 ? Math.round((progress.scanned / progress.total) * 100) : 0;

  const progressLabel = () => {
    if (progress.status === "done") {
      return `Завершено — найдено ${progress.found} устройств`;
    }
    if (progress.message) {
      return progress.message;
    }
    if (progress.scanned === progress.total && progress.total > 0) {
      return `Идентификация устройств (SNMP)… найдено: ${progress.found}`;
    }
    return `Сканирование: ${progress.scanned}/${progress.total}`;
  };

  return (
    <div className="space-y-6">
      {/* Scan controls */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        <div className="flex items-center gap-2 text-gray-900 font-medium">
          <Wifi className="h-5 w-5 text-blue-600" />
          Сканирование сети
        </div>

        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <label className="block text-xs font-medium text-gray-500 mb-1">Подсети (через запятую)</label>
            <input
              type="text"
              value={subnet}
              onChange={(e) => setSubnet(e.target.value)}
              placeholder="10.10.98.0/24, 10.10.99.0/24"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="sm:w-48">
            <label className="block text-xs font-medium text-gray-500 mb-1">Порты</label>
            <input
              type="text"
              value={ports}
              onChange={(e) => setPorts(e.target.value)}
              placeholder="9100,631,80"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="flex items-end">
            <button
              onClick={() => scanMut.mutate()}
              disabled={isScanning || !subnet}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition whitespace-nowrap"
            >
              {isScanning ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              {isScanning ? "Сканирование..." : "Сканировать"}
            </button>
          </div>
        </div>

        {/* Progress bar */}
        {(isScanning || progress.status === "done") && (
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-gray-500">
              <span>{progressLabel()}</span>
              <span>{pct}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className={`h-2 rounded-full transition-all duration-300 ${
                  progress.status === "done" ? "bg-emerald-500" : "bg-blue-500"
                }`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        {progress.status === "error" && progress.message && (
          <div className="flex items-center gap-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            {progress.message}
          </div>
        )}
      </div>

      {/* Results */}
      {devices.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-200 bg-gray-50">
            <h3 className="text-sm font-medium text-gray-700">
              Найденные устройства ({devices.length})
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    IP
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    MAC
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Порты
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Модель
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Статус
                  </th>
                  {isSuperuser && (
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      Действия
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {devices.map((dev) => (
                  <DeviceRow
                    key={dev.ip}
                    device={dev}
                    isSuperuser={isSuperuser}
                    onAdd={(d) =>
                      addMut.mutate({
                        store_name: "",
                        model: d.hostname || "Unknown",
                        ip_address: d.ip,
                        printer_type: d.open_ports.includes(9100) ? "label" : "laser",
                      })
                    }
                    onUpdateIp={(d) => {
                      if (d.known_printer_id) {
                        updateIpMut.mutate({
                          id: d.known_printer_id,
                          ip: d.ip,
                          mac: d.mac ?? undefined,
                        });
                      }
                    }}
                    isAdding={addMut.isPending}
                    isUpdating={updateIpMut.isPending}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {progress.status === "done" && devices.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <Monitor className="h-12 w-12 mx-auto mb-3 opacity-50" />
          <p className="text-lg">Устройства не найдены</p>
          <p className="text-sm mt-1">Попробуйте другую подсеть или порты</p>
        </div>
      )}

      {progress.status === "idle" && (
        <div className="text-center py-16 text-gray-400">
          <Wifi className="h-12 w-12 mx-auto mb-3 opacity-50" />
          <p className="text-lg">Введите подсеть и нажмите «Сканировать»</p>
          <p className="text-sm mt-1">
            Будет произведён поиск устройств с открытыми принтерными портами
          </p>
        </div>
      )}
    </div>
  );
}

function DeviceRow({
  device,
  isSuperuser,
  onAdd,
  onUpdateIp,
  isAdding,
  isUpdating,
}: {
  device: DiscoveredDevice;
  isSuperuser: boolean;
  onAdd: (d: DiscoveredDevice) => void;
  onUpdateIp: (d: DiscoveredDevice) => void;
  isAdding: boolean;
  isUpdating: boolean;
}) {
  const statusBadge = () => {
    if (device.ip_changed) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-700 px-2.5 py-0.5 text-xs font-medium">
          <ArrowRightLeft className="h-3 w-3" />
          IP сменился
        </span>
      );
    }
    if (device.is_known) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 text-emerald-700 px-2.5 py-0.5 text-xs font-medium">
          <CheckCircle2 className="h-3 w-3" />
          Известен
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 text-blue-700 px-2.5 py-0.5 text-xs font-medium">
        Новый
      </span>
    );
  };

  return (
    <tr className="hover:bg-gray-50 transition">
      <td className="px-4 py-3 text-sm font-mono text-gray-900">{device.ip}</td>
      <td className="px-4 py-3 text-sm font-mono text-gray-500">{device.mac || "—"}</td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {device.open_ports.join(", ")}
      </td>
      <td className="px-4 py-3 text-sm text-gray-700">
        {device.hostname ? (
          <span title={device.hostname}>
            {device.hostname.length > 40
              ? device.hostname.substring(0, 40) + "..."
              : device.hostname}
          </span>
        ) : (
          <span className="text-gray-400">—</span>
        )}
      </td>
      <td className="px-4 py-3">{statusBadge()}</td>
      {isSuperuser && (
        <td className="px-4 py-3 text-right">
          {device.ip_changed && device.known_printer_id && (
            <button
              onClick={() => onUpdateIp(device)}
              disabled={isUpdating}
              className="inline-flex items-center gap-1 rounded-lg bg-amber-50 border border-amber-200 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50 transition"
            >
              <ArrowRightLeft className="h-3 w-3" />
              Обновить IP
            </button>
          )}
          {!device.is_known && !device.ip_changed && (
            <button
              onClick={() => onAdd(device)}
              disabled={isAdding}
              className="inline-flex items-center gap-1 rounded-lg bg-blue-50 border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-50 transition"
            >
              <Plus className="h-3 w-3" />
              Добавить
            </button>
          )}
        </td>
      )}
    </tr>
  );
}
