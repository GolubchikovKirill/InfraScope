import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { NetworkSwitch, SwitchPort } from "../client";
import {
  getSwitchPorts,
  setSwitchPortAdminState,
  setSwitchPortDescription,
  setSwitchPortMode,
  setSwitchPortPoe,
  setSwitchPortVlan,
} from "../client";

interface Props {
  sw: NetworkSwitch;
  isSuperuser: boolean;
  onClose: () => void;
}

function formatStatus(value: string | null) {
  if (!value) return "—";
  if (value === "up") return "UP";
  if (value === "down") return "DOWN";
  return value;
}

export default function SwitchPortsTable({ sw, isSuperuser, onClose }: Props) {
  const [q, setQ] = useState("");
  const [activeTab, setActiveTab] = useState<"current" | "configure">("current");
  const [descDraft, setDescDraft] = useState<Record<string, string>>({});
  const [vlanDraft, setVlanDraft] = useState<Record<string, string>>({});
  const [modeDraft, setModeDraft] = useState<Record<string, "access" | "trunk">>({});
  const [nativeVlanDraft, setNativeVlanDraft] = useState<Record<string, string>>({});
  const [allowedVlansDraft, setAllowedVlansDraft] = useState<Record<string, string>>({});
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["switch-ports", sw.id, q],
    queryFn: () => getSwitchPorts(sw.id, q || undefined),
  });

  const rows = useMemo(() => {
    const source = data?.data ?? [];
    const rank = (status: string | null) => (status === "up" ? 0 : status === "down" ? 2 : 1);
    return [...source].sort((a, b) => rank(a.oper_status) - rank(b.oper_status));
  }, [data?.data]);
  const key = useMemo(() => ["switch-ports", sw.id, q] as const, [sw.id, q]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: key });
  };

  const adminMut = useMutation({
    mutationFn: ({ port, state }: { port: string; state: "up" | "down" }) =>
      setSwitchPortAdminState(sw.id, port, state),
    onSettled: refresh,
  });
  const descMut = useMutation({
    mutationFn: ({ port, description }: { port: string; description: string }) =>
      setSwitchPortDescription(sw.id, port, description),
    onSettled: refresh,
  });
  const vlanMut = useMutation({
    mutationFn: ({ port, vlan }: { port: string; vlan: number }) => setSwitchPortVlan(sw.id, port, vlan),
    onSettled: refresh,
  });
  const poeMut = useMutation({
    mutationFn: ({ port, action }: { port: string; action: "on" | "off" | "cycle" }) =>
      setSwitchPortPoe(sw.id, port, action),
    onSettled: refresh,
  });
  const modeMut = useMutation({
    mutationFn: (payload: {
      port: string;
      mode: "access" | "trunk";
      access_vlan?: number;
      native_vlan?: number;
      allowed_vlans?: string;
    }) => setSwitchPortMode(sw.id, payload.port, payload),
    onSettled: refresh,
  });

  const saveDescription = (row: SwitchPort) => {
    const draft = (descDraft[row.port] ?? row.description ?? "").trim();
    descMut.mutate({ port: row.port, description: draft });
  };
  const saveVlan = (row: SwitchPort) => {
    const value = Number(vlanDraft[row.port] ?? row.vlan ?? 1);
    if (Number.isNaN(value) || value < 1 || value > 4094) return;
    vlanMut.mutate({ port: row.port, vlan: value });
  };
  const saveMode = (row: SwitchPort) => {
    const mode = modeDraft[row.port] ?? (row.port_mode === "trunk" ? "trunk" : "access");
    if (mode === "access") {
      const accessVlan = Number(vlanDraft[row.port] ?? row.access_vlan ?? row.vlan ?? 1);
      if (Number.isNaN(accessVlan) || accessVlan < 1 || accessVlan > 4094) return;
      modeMut.mutate({ port: row.port, mode, access_vlan: accessVlan });
      return;
    }
    const nativeVlanRaw = nativeVlanDraft[row.port] ?? String(row.trunk_native_vlan ?? "");
    const nativeVlan = nativeVlanRaw ? Number(nativeVlanRaw) : undefined;
    if (nativeVlan !== undefined && (Number.isNaN(nativeVlan) || nativeVlan < 1 || nativeVlan > 4094)) return;
    const allowedVlans = (allowedVlansDraft[row.port] ?? row.trunk_allowed_vlans ?? "").trim() || undefined;
    modeMut.mutate({ port: row.port, mode, native_vlan: nativeVlan, allowed_vlans: allowedVlans });
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="app-panel w-full max-w-7xl max-h-[90vh] overflow-hidden border-slate-200/70 shadow-2xl">
        <div className="p-4 border-b border-slate-200 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">Порты: {sw.name}</h3>
            <p className="text-xs text-slate-500">{sw.ip_address} · {sw.vendor.toUpperCase()}</p>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Фильтр по порту/описанию"
              className="app-input px-3 py-2 text-sm w-64"
            />
            <button onClick={onClose} className="app-btn-secondary px-3 py-2 text-sm">
              Закрыть
            </button>
          </div>
        </div>
        <div className="px-4 pt-3">
          <div className="app-tabbar inline-flex gap-1 p-1.5">
            <button
              onClick={() => setActiveTab("current")}
              className={`app-tab px-3 py-1.5 text-xs font-medium ${activeTab === "current" ? "active" : "text-slate-500"}`}
            >
              Текущие настройки
            </button>
            <button
              onClick={() => setActiveTab("configure")}
              className={`app-tab px-3 py-1.5 text-xs font-medium ${activeTab === "configure" ? "active" : "text-slate-500"}`}
            >
              Перенастроить порты
            </button>
          </div>
        </div>
        <div className="overflow-auto max-h-[75vh]">
          {isLoading ? (
            <div className="p-8 text-sm text-gray-500 text-center">Загрузка портов...</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-slate-50 sticky top-0 z-10">
                {activeTab === "current" ? (
                  <tr className="text-left text-slate-600">
                    <th className="px-3 py-2">Port</th>
                    <th className="px-3 py-2">Name</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Vlan</th>
                    <th className="px-3 py-2">Mode</th>
                    <th className="px-3 py-2">Duplex</th>
                    <th className="px-3 py-2">Speed</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">PoE</th>
                  </tr>
                ) : (
                  <tr className="text-left text-slate-600">
                    <th className="px-3 py-2">Порт</th>
                    <th className="px-3 py-2">Admin/Oper</th>
                    <th className="px-3 py-2">Mode/VLAN</th>
                    <th className="px-3 py-2">Speed</th>
                    <th className="px-3 py-2">PoE</th>
                    <th className="px-3 py-2">Описание</th>
                    <th className="px-3 py-2">Операции</th>
                  </tr>
                )}
              </thead>
              <tbody>
                {rows.map((row) => {
                  const modeValue =
                    row.port_mode ??
                    (row.vlan_text === "trunk"
                      ? "trunk"
                      : row.vlan_text && /^\d+$/.test(row.vlan_text)
                        ? "access"
                        : row.trunk_allowed_vlans
                          ? "trunk"
                          : row.access_vlan !== null
                            ? "access"
                            : "—");
                  const vlanValue =
                    row.vlan_text ??
                    (row.vlan !== null
                      ? String(row.vlan)
                      : row.access_vlan !== null
                        ? String(row.access_vlan)
                        : row.port_mode === "trunk" || row.trunk_allowed_vlans
                          ? "trunk"
                          : "—");
                  const duplexValue = row.duplex_text ?? row.duplex ?? "—";
                  const speedValue = row.speed_text ?? (row.speed_mbps ? `${row.speed_mbps} Mbps` : "—");
                  const typeValue = row.media_type ?? "—";

                  if (activeTab === "current") {
                    return (
                      <tr key={row.port} className="border-t border-slate-100 align-top hover:bg-slate-50/60">
                        <td className="px-3 py-2 font-mono">{row.port}</td>
                        <td className="px-3 py-2 text-slate-700">{row.description || "—"}</td>
                        <td className="px-3 py-2">{row.status_text ?? formatStatus(row.oper_status)}</td>
                        <td className="px-3 py-2">{vlanValue}</td>
                        <td className="px-3 py-2">{modeValue}</td>
                        <td className="px-3 py-2">{duplexValue}</td>
                        <td className="px-3 py-2">{speedValue}</td>
                        <td className="px-3 py-2">{typeValue}</td>
                        <td className="px-3 py-2">
                          <div>{row.poe_enabled === null ? "—" : row.poe_enabled ? "on" : "off"}</div>
                          <div className="text-gray-400">{row.poe_power_w ?? "—"} W</div>
                        </td>
                      </tr>
                    );
                  }

                  return (
                    <tr key={row.port} className="border-t border-slate-100 align-top hover:bg-slate-50/60">
                      <td className="px-3 py-2 font-mono">{row.port}</td>
                      <td className="px-3 py-2">{formatStatus(row.admin_status)} / {formatStatus(row.oper_status)}</td>
                      <td className="px-3 py-2">
                        <div className="space-y-1">
                          <div className="text-[11px] text-slate-500">
                            current: {row.port_mode ?? "unknown"}
                            {row.port_mode === "access" && (row.access_vlan ?? row.vlan) ? ` / VLAN ${row.access_vlan ?? row.vlan}` : ""}
                            {row.port_mode === "trunk" && row.trunk_native_vlan ? ` / native ${row.trunk_native_vlan}` : ""}
                          </div>
                          {row.port_mode === "trunk" && row.trunk_allowed_vlans && (
                            <div className="text-[11px] text-slate-500">allowed: {row.trunk_allowed_vlans}</div>
                          )}
                          {isSuperuser && (
                            <div className="flex flex-wrap items-center gap-1">
                              <select
                                value={modeDraft[row.port] ?? (row.port_mode === "trunk" ? "trunk" : "access")}
                                onChange={(e) =>
                                  setModeDraft((prev) => ({ ...prev, [row.port]: e.target.value as "access" | "trunk" }))
                                }
                                className="app-input px-2 py-1 text-xs"
                              >
                                <option value="access">access</option>
                                <option value="trunk">trunk</option>
                              </select>
                              <input
                                value={vlanDraft[row.port] ?? String(row.access_vlan ?? row.vlan ?? "")}
                                onChange={(e) => setVlanDraft((prev) => ({ ...prev, [row.port]: e.target.value }))}
                                placeholder="access vlan"
                                className="app-input w-20 px-2 py-1 text-xs"
                              />
                              <input
                                value={nativeVlanDraft[row.port] ?? String(row.trunk_native_vlan ?? "")}
                                onChange={(e) => setNativeVlanDraft((prev) => ({ ...prev, [row.port]: e.target.value }))}
                                placeholder="native"
                                className="app-input w-20 px-2 py-1 text-xs"
                              />
                              <input
                                value={allowedVlansDraft[row.port] ?? row.trunk_allowed_vlans ?? ""}
                                onChange={(e) => setAllowedVlansDraft((prev) => ({ ...prev, [row.port]: e.target.value }))}
                                placeholder="allowed vlans"
                                className="app-input w-28 px-2 py-1 text-xs"
                              />
                              <button onClick={() => saveMode(row)} className="app-btn-secondary px-2 py-1 text-xs">
                                Apply
                              </button>
                              <button onClick={() => saveVlan(row)} className="app-btn-secondary px-2 py-1 text-xs">
                                Set VLAN
                              </button>
                            </div>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2">{speedValue}</td>
                      <td className="px-3 py-2">
                        <div>{row.poe_enabled === null ? "—" : row.poe_enabled ? "on" : "off"}</div>
                        <div className="text-gray-400">{row.poe_power_w ?? "—"} W</div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1">
                          <input
                            value={descDraft[row.port] ?? row.description ?? ""}
                            onChange={(e) => setDescDraft((prev) => ({ ...prev, [row.port]: e.target.value }))}
                            className="app-input w-52 px-2 py-1 text-xs"
                          />
                          {isSuperuser && (
                            <button
                              onClick={() => saveDescription(row)}
                              className="app-btn-secondary px-2 py-1 text-xs"
                            >
                              Save
                            </button>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        {isSuperuser ? (
                          <div className="flex flex-wrap gap-1">
                            <button
                              onClick={() => adminMut.mutate({ port: row.port, state: "up" })}
                              className="px-2 py-1 rounded border border-green-200 text-green-700 hover:bg-green-50"
                            >
                              Up
                            </button>
                            <button
                              onClick={() => adminMut.mutate({ port: row.port, state: "down" })}
                              className="px-2 py-1 rounded border border-red-200 text-red-700 hover:bg-red-50"
                            >
                              Down
                            </button>
                            <button
                              onClick={() => poeMut.mutate({ port: row.port, action: "cycle" })}
                              className="px-2 py-1 rounded border border-amber-200 text-amber-700 hover:bg-amber-50"
                            >
                              PoE cycle
                            </button>
                            <button
                              onClick={() => poeMut.mutate({ port: row.port, action: "on" })}
                              className="px-2 py-1 rounded border border-indigo-200 text-indigo-700 hover:bg-indigo-50"
                            >
                              PoE on
                            </button>
                            <button
                              onClick={() => poeMut.mutate({ port: row.port, action: "off" })}
                              className="px-2 py-1 rounded border border-gray-300 text-gray-700 hover:bg-gray-50"
                            >
                              PoE off
                            </button>
                          </div>
                        ) : (
                          <span className="text-gray-400">read-only</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
