import api from "./http";

export interface NetworkSwitch {
  id: string;
  name: string;
  ip_address: string;
  ssh_username: string;
  ssh_port: number;
  ap_vlan: number;
  vendor: "cisco" | "dlink" | "generic";
  management_protocol: "snmp" | "ssh" | "snmp+ssh";
  snmp_version: "2c";
  snmp_community_ro?: string | null;
  snmp_community_rw?: string | null;
  model_info: string | null;
  ios_version: string | null;
  hostname: string | null;
  uptime: string | null;
  is_online: boolean | null;
  reachability_reason: string | null;
  last_polled_at: string | null;
  mac_address: string | null;
  mac_status: string | null;
  auto_reboot_aps_enabled: boolean;
  auto_reboot_mode: "dry_run" | "live";
  dhcp_clear_enabled: boolean;
  dhcp_clear_mode: "dry_run" | "live";
  switch_needs_attention_since: string | null;
  created_at: string;
}

export interface NetworkSwitchesResponse {
  data: NetworkSwitch[];
  count: number;
}

export interface AccessPoint {
  mac_address: string;
  port: string;
  vlan: number;
  ip_address: string | null;
  cdp_name: string | null;
  cdp_platform: string | null;
  poe_power: string | null;
  poe_status: string | null;
  // From the persistent AP registry: false means known from a past scan but
  // silent on this scan - a hang signal a live-only scan can't show.
  is_responding: boolean;
  last_seen_at: string | null;
  exclude_from_auto_reboot: boolean;
  consecutive_reboot_failures: number;
  consecutive_no_power_skips: number;
  needs_attention_since: string | null;
}

export interface CameraPort {
  port: string;
  vlan: number;
  oper_status: string;
  description: string | null;
  poe_power: string | null;
  poe_status: string | null;
  /** no link and no PoE draw: nothing plugged in (a hung camera still draws power) */
  empty?: boolean;
}

export interface SwitchPort {
  port: string;
  if_index: number;
  description: string | null;
  admin_status: string | null;
  oper_status: string | null;
  status_text: string | null;
  vlan_text: string | null;
  duplex_text: string | null;
  speed_text: string | null;
  media_type: string | null;
  speed_mbps: number | null;
  duplex: string | null;
  vlan: number | null;
  port_mode: string | null;
  access_vlan: number | null;
  trunk_native_vlan: number | null;
  trunk_allowed_vlans: string | null;
  poe_enabled: boolean | null;
  poe_power_w: number | null;
  mac_count: number | null;
}

export interface SwitchPortsResponse {
  data: SwitchPort[];
  count: number;
}

export async function getSwitches(name?: string) {
  const params: Record<string, string> = {};
  if (name) params.name = name;
  const { data } = await api.get<NetworkSwitchesResponse>("/switches/", { params });
  return data;
}

export async function createSwitch(sw: {
  name: string;
  ip_address: string;
  ssh_username: string;
  ssh_password: string;
  enable_password: string;
  ssh_port: number;
  ap_vlan: number;
  vendor: "cisco" | "dlink" | "generic";
  management_protocol: "snmp" | "ssh" | "snmp+ssh";
  snmp_version: "2c";
  snmp_community_ro: string;
  snmp_community_rw?: string;
}) {
  const { data } = await api.post<NetworkSwitch>("/switches/", sw);
  return data;
}

export async function updateSwitch(id: string, sw: Record<string, unknown>) {
  const { data } = await api.patch<NetworkSwitch>(`/switches/${id}`, sw);
  return data;
}

export async function deleteSwitch(id: string) {
  await api.delete(`/switches/${id}`);
}

export async function pollSwitch(id: string) {
  const { data } = await api.post<NetworkSwitch>(`/switches/${id}/poll`);
  return data;
}

export async function pollAllSwitches() {
  await api.post("/switches/poll-all");
}

export async function getSwitchAPs(id: string) {
  const { data } = await api.get<AccessPoint[]>(`/switches/${id}/access-points`);
  return data;
}

export async function getSwitchCameraPorts(id: string) {
  const { data } = await api.get<CameraPort[]>(`/switches/${id}/camera-ports`);
  return data;
}

export async function rebootCameraPort(id: string, port: string) {
  const encoded = encodeURIComponent(port);
  const { data } = await api.post<{ status: string; port: string; back_online: boolean }>(
    `/switches/${id}/camera-ports/${encoded}/reboot`,
  );
  return data;
}

export interface CameraSweepResult {
  status: "done" | "failed" | "busy" | "unreachable" | "no_cameras" | "no_camera_vlans" | string;
  rebooted_count?: number;
  failed_count?: number;
  back_online_count?: number;
  skipped_empty?: number;
  failed_ports?: string[];
  not_back_ports?: string[];
}

interface TaskStatus {
  state: string;
  ready: boolean;
  successful: boolean | null;
  result: CameraSweepResult | null;
  error: string | null;
}

/** Queue the store-wide camera sweep and wait for the worker to finish it.
 *  It takes minutes (one camera at a time, then a link check), so the request
 *  only queues it and this follows the task until it is done. */
export async function rebootAllCameraPorts(
  id: string,
  { pollMs = 5_000, maxWaitMs = 60 * 60_000 }: { pollMs?: number; maxWaitMs?: number } = {},
): Promise<CameraSweepResult> {
  const { data } = await api.post<{ status: string; task_id: string }>(`/switches/${id}/camera-ports/reboot-all`);
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, pollMs));
    const { data: task } = await api.get<TaskStatus>(`/tasks/${data.task_id}`);
    if (!task.ready) continue;
    if (!task.successful) throw new Error(task.error || "Перезагрузка камер завершилась с ошибкой");
    return task.result ?? { status: "failed" };
  }
  throw new Error("Перезагрузка камер всё ещё идёт — результат появится в журнале событий");
}

export async function rebootAP(switchId: string, iface: string, macAddress?: string, method: string = "poe") {
  const { data } = await api.post<{ status: string; interface: string; method: string; back_online?: boolean }>(
    `/switches/${switchId}/reboot-ap`,
    { interface: iface, method, mac_address: macAddress },
  );
  return data;
}

export async function setApExcluded(switchId: string, macAddress: string, excluded: boolean) {
  const encoded = encodeURIComponent(macAddress);
  const { data } = await api.patch(`/switches/${switchId}/access-points/${encoded}/exclude`, { excluded });
  return data as { message: string };
}

export async function runAutoRebootNow(switchId: string) {
  const { data } = await api.post(`/switches/${switchId}/auto-reboot/run`);
  return data;
}

export interface AutoRebootSummary {
  last_cycle_at: string | null;
  window_hours: number;
  switches_processed: number;
  aps_rebooted_ok: number;
  aps_failed: number;
  switches_skipped: number;
  aps_needing_attention: number;
  switches_needing_attention: number;
}

export async function getAutoRebootSummary(hours = 24) {
  const { data } = await api.get<AutoRebootSummary>("/switches/auto-reboot/summary", { params: { hours } });
  return data;
}

export interface AutoRebootHistoryEntry {
  created_at: string;
  severity: string;
  event_type: string;
  message: string;
}

export async function getAutoRebootHistory(switchId: string, limit = 50) {
  const { data } = await api.get<AutoRebootHistoryEntry[]>(`/switches/${switchId}/auto-reboot/history`, {
    params: { limit },
  });
  return data;
}

export type DhcpRole = "local_server" | "relay" | "external";

export interface DhcpBinding {
  ip_address: string;
  client_id: string;
  lease_expiration: string;
  binding_type: string;
  state: string | null;
  interface: string | null;
}

export interface DhcpPool {
  name: string;
  total_addresses: number | null;
  leased_addresses: number | null;
  ranges: [string, string][];
}

export interface DhcpDiagnostics {
  vlan: number;
  role: DhcpRole;
  pools: DhcpPool[];
  bindings_total: number;
  ap_bindings: DhcpBinding[];
  conflicts: string[];
  helper_addresses: string[];
  svi_ip: string | null;
  snooping_enabled: boolean | null;
  snooping_vlans: number[];
  arp_inspection_vlans: number[];
  ip_source_guard: boolean;
  unsupported: string[];
  planned_commands: string[];
  skipped_reasons: string[];
}

export async function getSwitchDhcp(switchId: string) {
  const { data } = await api.get<DhcpDiagnostics>(`/switches/${switchId}/dhcp`);
  return data;
}

export interface DhcpClearResult {
  switch: string;
  mode: "dry_run" | "live";
  role: DhcpRole | null;
  skipped: string[] | string | null;
  commands_planned: number;
  bindings_before: number;
  conflicts_before: number;
  bindings_cleared: number | null;
  conflicts_cleared: number | null;
  bindings_after: number | null;
  conflicts_after: number | null;
  errors: string[];
}

export async function runDhcpClearNow(switchId: string) {
  const { data } = await api.post<DhcpClearResult>(`/switches/${switchId}/dhcp/clear`);
  return data;
}

export async function getSwitchPorts(id: string, q?: string, skip = 0, limit = 100) {
  const params: Record<string, string | number> = { skip, limit };
  if (q) params.q = q;
  const { data } = await api.get<SwitchPortsResponse>(`/switches/${id}/ports`, { params });
  return data;
}

export async function setSwitchPortAdminState(id: string, port: string, admin_state: "up" | "down") {
  const encoded = encodeURIComponent(port);
  const { data } = await api.post(`/switches/${id}/ports/${encoded}/admin-state`, { admin_state });
  return data as { message: string };
}

export async function setSwitchPortDescription(id: string, port: string, description: string) {
  const encoded = encodeURIComponent(port);
  const { data } = await api.post(`/switches/${id}/ports/${encoded}/description`, { description });
  return data as { message: string };
}

export async function setSwitchPortVlan(id: string, port: string, vlan: number) {
  const encoded = encodeURIComponent(port);
  const { data } = await api.post(`/switches/${id}/ports/${encoded}/vlan`, { vlan });
  return data as { message: string };
}

export async function setSwitchPortPoe(id: string, port: string, action: "on" | "off" | "cycle") {
  const encoded = encodeURIComponent(port);
  const { data } = await api.post(`/switches/${id}/ports/${encoded}/poe`, { action });
  return data as { message: string };
}

export async function setSwitchPortMode(
  id: string,
  port: string,
  payload: {
    mode: "access" | "trunk";
    access_vlan?: number;
    native_vlan?: number;
    allowed_vlans?: string;
  },
) {
  const encoded = encodeURIComponent(port);
  const { data } = await api.post(`/switches/${id}/ports/${encoded}/mode`, payload);
  return data as { message: string };
}
