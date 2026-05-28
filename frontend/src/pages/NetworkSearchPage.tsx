import { useEffect, useMemo, useRef, useState } from "react";
import { Plus, Radar, RefreshCw, Search, X } from "lucide-react";
import {
  addDiscoveredIconbit,
  addDiscoveredPrinter,
  addDiscoveredSwitch,
  createCashRegister,
  createComputer,
  getIconbitDiscoveryResults,
  getScanResults,
  getScannerSettings,
  getSwitchDiscoveryResults,
  smartSearchCashRegistersInNetwork,
  smartSearchComputersInNetwork,
  startIconbitDiscoveryScan,
  startScan,
  startSwitchDiscoveryScan,
  type SmartNetworkCandidate,
  type DiscoveredDevice,
  type DiscoveredNetworkDevice,
} from "../client";
import { useAuth } from "../auth";

type SearchTarget = "computers" | "cash-registers" | "media-players" | "switches" | "printers";

type SearchRow = {
  ip: string;
  hostname: string | null;
  mac: string | null;
  open_ports: number[];
  model_info: string | null;
  vendor: string | null;
  confidence: string;
  reason: string;
};

const TARGET_LABELS: Record<SearchTarget, string> = {
  computers: "Компьютеры",
  "cash-registers": "Кассы",
  "media-players": "Медиаплееры",
  switches: "Свитчи",
  printers: "Принтеры",
};

const DEFAULT_PORTS: Record<SearchTarget, string> = {
  computers: "445,3389,135",
  "cash-registers": "5405,445,3389",
  "media-players": "8081,80,443",
  switches: "22,161,80,443",
  printers: "9100,631,80,443",
};

const DEFAULT_FILTER: Record<SearchTarget, string> = {
  computers: "-MGR-",
  "cash-registers": "KKM",
  "media-players": "",
  switches: "",
  printers: "",
};

const LAT_TO_CYR = new Map<string, string>([
  ["A", "А"], ["a", "а"], ["B", "В"], ["E", "Е"], ["e", "е"], ["K", "К"], ["k", "к"], ["M", "М"],
  ["H", "Н"], ["h", "н"], ["O", "О"], ["o", "о"], ["P", "Р"], ["p", "р"], ["C", "С"], ["c", "с"],
  ["T", "Т"], ["t", "т"], ["X", "Х"], ["x", "х"], ["Y", "У"], ["y", "у"],
]);

function normalizeSmartText(value: string): string {
  return value
    .split("")
    .map((ch) => LAT_TO_CYR.get(ch) ?? ch)
    .join("")
    .toLowerCase();
}

function smartIncludes(haystack: string, needle: string): boolean {
  if (!needle.trim()) return true;
  const h = normalizeSmartText(haystack);
  const tokens = needle
    .split(/\s+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map(normalizeSmartText);
  return tokens.every((token) => h.includes(token));
}

async function pollDiscoveryResults(
  reader: () => Promise<{ progress: { status: string }; devices: Array<DiscoveredDevice | DiscoveredNetworkDevice> }>,
  shouldContinue: () => boolean,
  attempts = 40,
): Promise<Array<DiscoveredDevice | DiscoveredNetworkDevice>> {
  for (let i = 0; i < attempts; i += 1) {
    if (!shouldContinue()) return [];
    const payload = await reader();
    if (payload.progress.status === "done") return payload.devices;
    if (payload.progress.status === "error") return payload.devices;
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  if (!shouldContinue()) return [];
  const payload = await reader();
  return payload.devices;
}

function toRowsFromSmart(items: SmartNetworkCandidate[]): SearchRow[] {
  return items.map((item) => ({
    ip: item.ip,
    hostname: item.hostname,
    mac: null,
    open_ports: item.open_ports,
    model_info: null,
    vendor: null,
    confidence: item.confidence,
    reason: item.reason,
  }));
}

function toRowsFromDiscovery(items: Array<DiscoveredDevice | DiscoveredNetworkDevice>): SearchRow[] {
  return items.map((item) => ({
    ip: item.ip,
    hostname: item.hostname ?? null,
    mac: item.mac ?? null,
    open_ports: item.open_ports ?? [],
    model_info: "model_info" in item ? item.model_info ?? null : null,
    vendor: "vendor" in item ? item.vendor ?? null : null,
    confidence: item.open_ports?.length ? "medium" : "low",
    reason: item.open_ports?.length ? "Обнаружены открытые порты" : "Найдено по сети",
  }));
}

export default function NetworkSearchPage() {
  const { user } = useAuth();
  const isSuperuser = Boolean(user?.is_superuser);
  const [target, setTarget] = useState<SearchTarget>("computers");
  const [subnet, setSubnet] = useState("");
  const [ports, setPorts] = useState(DEFAULT_PORTS.computers);
  const [hostnameFilter, setHostnameFilter] = useState(DEFAULT_FILTER.computers);
  const [limit, setLimit] = useState(300);
  const [results, setResults] = useState<SearchRow[]>([]);
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addingKey, setAddingKey] = useState<string | null>(null);
  const scanRunRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      scanRunRef.current += 1;
    };
  }, []);

  useEffect(() => {
    getScannerSettings()
      .then((data) => {
        if (!subnet) {
          setSubnet(data.subnet || "");
        }
      })
      .catch(() => {
        // ignore settings prefill errors
      });
  }, [subnet]);

  useEffect(() => {
    setPorts(DEFAULT_PORTS[target]);
    setHostnameFilter(DEFAULT_FILTER[target]);
    setResults([]);
    setError(null);
  }, [target]);

  const filteredResults = useMemo(() => {
    if (!hostnameFilter.trim()) return results;
    return results.filter((row) => smartIncludes(`${row.hostname ?? ""} ${row.ip}`, hostnameFilter));
  }, [results, hostnameFilter]);

  const runSearch = async () => {
    const runId = scanRunRef.current + 1;
    scanRunRef.current = runId;
    const isCurrentRun = () => mountedRef.current && scanRunRef.current === runId;
    setIsScanning(true);
    setError(null);
    setResults([]);
    try {
      if (target === "computers") {
        const payload = await smartSearchComputersInNetwork({
          subnet: subnet || undefined,
          ports: ports || undefined,
          hostname_contains: hostnameFilter || undefined,
          limit,
        });
        if (!isCurrentRun()) return;
        setResults(toRowsFromSmart(payload.data));
        return;
      }
      if (target === "cash-registers") {
        const payload = await smartSearchCashRegistersInNetwork({
          subnet: subnet || undefined,
          ports: ports || undefined,
          hostname_contains: hostnameFilter || undefined,
          limit,
        });
        if (!isCurrentRun()) return;
        setResults(toRowsFromSmart(payload.data));
        return;
      }
      if (target === "media-players") {
        await startIconbitDiscoveryScan(subnet, ports);
        const devices = await pollDiscoveryResults(getIconbitDiscoveryResults, isCurrentRun);
        if (!isCurrentRun()) return;
        setResults(toRowsFromDiscovery(devices));
        return;
      }
      if (target === "switches") {
        await startSwitchDiscoveryScan(subnet, ports);
        const devices = await pollDiscoveryResults(getSwitchDiscoveryResults, isCurrentRun);
        if (!isCurrentRun()) return;
        setResults(toRowsFromDiscovery(devices));
        return;
      }
      await startScan(subnet, ports);
      const devices = await pollDiscoveryResults(getScanResults, isCurrentRun);
      if (!isCurrentRun()) return;
      setResults(toRowsFromDiscovery(devices));
    } catch (e) {
      if (!isCurrentRun()) return;
      const msg = e instanceof Error ? e.message : "Не удалось выполнить поиск";
      setError(msg);
    } finally {
      if (isCurrentRun()) {
        setIsScanning(false);
      }
    }
  };

  const addToTarget = async (row: SearchRow) => {
    const key = `${row.ip}-${row.hostname ?? "no-host"}`;
    setAddingKey(key);
    setError(null);
    try {
      if (target === "computers") {
        await createComputer({
          hostname: (row.hostname || row.ip).trim(),
          location: "",
          comment: "Добавлено из поиска в сети",
        });
        return;
      }
      if (target === "cash-registers") {
        const host = (row.hostname || row.ip).trim();
        const digits = host.match(/\d+/g)?.join("") ?? "";
        await createCashRegister({
          kkm_number: digits || host,
          hostname: host,
          kkm_type: "retail",
          comment: "Добавлено из поиска в сети",
        });
        return;
      }
      if (target === "media-players") {
        await addDiscoveredIconbit({
          ip_address: row.ip,
          name: row.hostname || `Media-${row.ip}`,
          model: row.model_info || "Iconbit",
          mac_address: row.mac || undefined,
        });
        return;
      }
      if (target === "switches") {
        const vendor = (row.vendor || "generic").toLowerCase();
        await addDiscoveredSwitch({
          ip_address: row.ip,
          name: row.hostname || `Switch-${row.ip}`,
          hostname: row.hostname || undefined,
          vendor: vendor === "cisco" || vendor === "dlink" || vendor === "generic" ? vendor : "generic",
        });
        return;
      }
      await addDiscoveredPrinter({
        store_name: "Новый магазин",
        model: row.model_info || row.hostname || "Новый принтер",
        ip_address: row.ip,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Не удалось добавить устройство";
      setError(msg);
    } finally {
      setAddingKey(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="app-panel p-4 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
          <label className="text-sm">
            <span className="mb-1 block text-slate-600">Что искать</span>
            <select
              className="app-input w-full py-2 px-3 text-sm"
              value={target}
              onChange={(e) => setTarget(e.target.value as SearchTarget)}
            >
              <option value="computers">Компьютеры</option>
              <option value="cash-registers">Кассы</option>
              <option value="media-players">Медиаплееры</option>
              <option value="switches">Свитчи</option>
              <option value="printers">Принтеры</option>
            </select>
          </label>
          <Input label="Подсеть (CIDR или список)" value={subnet} onChange={setSubnet} placeholder="10.10.98.0/24" />
          <Input label="Порты" value={ports} onChange={setPorts} placeholder={DEFAULT_PORTS[target]} />
          <label className="text-sm">
            <span className="mb-1 block text-slate-600">Лимит результатов</span>
            <input
              type="number"
              min={10}
              max={2000}
              className="app-input w-full py-2 px-3 text-sm"
              value={limit}
              onChange={(e) => setLimit(Math.max(10, Math.min(2000, Number(e.target.value) || 10)))}
            />
          </label>
        </div>
        <div className="relative max-w-2xl">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            value={hostnameFilter}
            onChange={(e) => setHostnameFilter(e.target.value)}
            placeholder="Доп. фильтр hostname/IP (умный A/А)"
            className="app-input w-full pl-10 pr-4 py-2 text-sm"
          />
        </div>
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="text-xs text-slate-500">
            Текущий режим: <span className="font-medium">{TARGET_LABELS[target]}</span>. Кнопка добавления отправляет устройство именно в этот раздел.
          </div>
          <div className="app-toolbar-actions flex flex-wrap gap-2">
            <button
              onClick={runSearch}
              disabled={isScanning}
              className="app-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm"
            >
              <Radar className={`h-4 w-4 ${isScanning ? "animate-spin" : ""}`} />
              {isScanning ? "Сканирование..." : "Запустить поиск"}
            </button>
            <button
              onClick={() => {
                setResults([]);
                setError(null);
              }}
              className="app-btn-secondary inline-flex items-center gap-2 px-4 py-2 text-sm"
            >
              <X className="h-4 w-4" />
              Очистить
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="app-panel p-4 text-sm text-rose-700 bg-rose-50 border-rose-200">
          Ошибка: {error}
        </div>
      )}

      <div className="app-panel p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-slate-900">
            Результаты поиска: {filteredResults.length}
          </div>
          {isScanning && (
            <div className="inline-flex items-center gap-2 text-xs text-slate-500">
              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              Идет сканирование...
            </div>
          )}
        </div>

        {filteredResults.length === 0 ? (
          <div className="text-sm text-slate-500">Запустите поиск, чтобы увидеть найденные устройства.</div>
        ) : (
          <div className="space-y-2">
            {filteredResults.slice(0, limit).map((row) => {
              const key = `${row.ip}-${row.hostname ?? "no-host"}`;
              return (
                <div key={key} className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                  <div className="text-xs text-gray-600">
                    <div className="font-medium text-slate-900">{row.hostname || "hostname не найден"}</div>
                    <div>
                      IP: {row.ip} · MAC: {row.mac || "—"} · Порты:{" "}
                      {row.open_ports.length ? row.open_ports.join(", ") : "—"}
                    </div>
                    <div>
                      confidence: {row.confidence} · {row.reason}
                    </div>
                  </div>
                  {isSuperuser && (
                    <button
                      onClick={() => addToTarget(row)}
                      disabled={addingKey === key}
                      className="app-btn-secondary inline-flex items-center gap-2 px-3 py-1.5 text-xs"
                    >
                      <Plus className="h-3.5 w-3.5" />
                      {addingKey === key ? "Добавление..." : `Добавить в "${TARGET_LABELS[target]}"`}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function Input({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="text-sm">
      <span className="mb-1 block text-slate-600">{label}</span>
      <input
        className="app-input w-full py-2 px-3 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </label>
  );
}
