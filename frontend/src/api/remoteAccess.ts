import api from "./http";

export type DeployState =
  | "unknown"
  | "not_installed"
  | "queued"
  | "installing"
  | "installed"
  | "configured"
  | "drift"
  | "failed"
  | "uninstalled";

export type DeployAction =
  | "deploy"
  | "reconfigure"
  | "rotate_password"
  | "set_lockdown"
  | "uninstall";

export type SourceKind = "cash_register" | "computer" | "media_player";

export interface RemoteDevice {
  id: string;
  hostname: string;
  location: string | null;
  source_kind: SourceKind;
  computer_id: string | null;
  media_player_id: string | null;
  cash_register_id: string | null;
  rustdesk_id: string | null;
  has_password: boolean;
  password_rotated_at: string | null;
  password_confirmed_at: string | null;
  desired_hidden: boolean;
  desired_block_outgoing: boolean;
  desired_unattended: boolean;
  managed: boolean;
  deploy_state: DeployState;
  deploy_detail: string | null;
  installed_version: string | null;
  online: boolean | null;
  logged_in_user: string | null;
  last_ip: string | null;
  last_seen_at: string | null;
  host_online: boolean | null;
  host_last_seen_at: string | null;
  last_deployed_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface AgentHealth {
  queued: number;
  running: number;
  last_claim_at: string | null;
  agent_stalled: boolean;
  console_ok: boolean;
}

export async function getAgentHealth() {
  const { data } = await api.get<AgentHealth>("/remote-access/health");
  return data;
}

export interface RemoteDevicesResponse {
  data: RemoteDevice[];
  count: number;
}

export interface DeployJob {
  id: string;
  device_id: string;
  hostname: string;
  action: string;
  status: string;
  attempts: number;
  claimed_by: string | null;
  started_at: string | null;
  finished_at: string | null;
  result_detail: string | null;
  created_by: string | null;
  created_at: string;
}

export async function getRemoteDevices(params?: {
  q?: string;
  location?: string;
  source_kind?: SourceKind;
  state?: string;
  hostnames?: string;
}) {
  const { data } = await api.get<RemoteDevicesResponse>("/remote-access/devices", { params });
  return data;
}

export interface PrepareResult {
  device: RemoteDevice;
  job: DeployJob | null;
}

/** Install + configure RustDesk on one endpoint, setting its id/password inline.
 *  Backs the "Деплой RustDesk" button on the device cards. */
export async function prepareRustDesk(payload: {
  hostname: string;
  rustdesk_id?: string;
  permanent_password?: string;
  action?: "deploy" | "reconfigure";
}) {
  const { data } = await api.post<PrepareResult>("/remote-access/devices/prepare", payload);
  return data;
}

/** Mirror of service._hostname_to_rid: RustDesk custom IDs allow only [A-Za-z0-9_]. */
export function hostnameToRid(hostname: string): string {
  return Array.from(hostname)
    .map((c) => (/[A-Za-z0-9]/.test(c) ? c : "_"))
    .join("")
    .slice(0, 32);
}

export async function updateRemoteDevice(id: string, payload: Partial<RemoteDevice>) {
  const { data } = await api.patch<RemoteDevice>(`/remote-access/devices/${id}`, payload);
  return data;
}

export async function rotateRemotePassword(id: string) {
  const { data } = await api.post<DeployJob>(`/remote-access/devices/${id}/rotate-password`);
  return data;
}

export async function syncRemoteAccess() {
  const { data } = await api.post<{ message: string }>("/remote-access/sync");
  return data;
}

export async function deployRemoteAccess(payload: {
  action: DeployAction;
  device_ids?: string[];
  location?: string;
  source_kind?: SourceKind;
  all_managed?: boolean;
}) {
  const { data } = await api.post<{ data: DeployJob[]; count: number }>("/remote-access/deploy", payload);
  return data;
}

export async function getRemoteJobs(params?: { status?: string; limit?: number }) {
  const { data } = await api.get<{ data: DeployJob[]; count: number }>("/remote-access/jobs", { params });
  return data;
}

export interface ConsoleConnection {
  id?: number;
  from_peer?: string;
  from_name?: string;
  peer_id?: string;
  ip?: string;
  action?: string;
  created_at?: string;
  close_time?: string;
}

export async function getConsoleConnections(limit = 200) {
  const { data } = await api.get<ConsoleConnection[]>("/remote-access/console/connections", {
    params: { limit },
  });
  return data;
}

export interface ConsoleAddressBookEntry {
  id: string;
  alias?: string | null;
  hostname?: string | null;
  username?: string | null;
  platform?: string | null;
  tags?: string[];
  online?: boolean | null;
}

export async function getConsoleAddressBook() {
  const { data } = await api.get<ConsoleAddressBookEntry[]>("/remote-access/console/address-book");
  return data;
}

export interface ConsoleUser {
  id?: number;
  username?: string;
  email?: string;
  is_admin?: boolean;
  status?: number;
}

export async function getConsoleUsers() {
  const { data } = await api.get<ConsoleUser[]>("/remote-access/console/users");
  return data;
}

/** Deep link the browser hands to the installed RustDesk client.
 *  The id goes in the PATH, not the authority - browsers lowercase the authority
 *  component and RustDesk IDs are case-sensitive (VNA_MGR_101 != vna_mgr_101). */
export function rustdeskLink(id: string): string {
  return `rustdesk://connection/new/${encodeURIComponent(id)}`;
}
