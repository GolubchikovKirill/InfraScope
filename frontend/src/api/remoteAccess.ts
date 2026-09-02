import api from "./http";

export type DeployState =
  | "unknown"
  | "not_installed"
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

export interface RemoteDevice {
  id: string;
  hostname: string;
  location: string | null;
  computer_id: string | null;
  media_player_id: string | null;
  rustdesk_id: string | null;
  has_password: boolean;
  password_rotated_at: string | null;
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
  last_deployed_at: string | null;
  last_error: string | null;
  created_at: string;
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
  state?: string;
}) {
  const { data } = await api.get<RemoteDevicesResponse>("/remote-access/devices", { params });
  return data;
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

/** Deep link the browser hands to the installed RustDesk client.
 *  The id goes in the PATH, not the authority - browsers lowercase the authority
 *  component and RustDesk IDs are case-sensitive (VNA_MGR_101 != vna_mgr_101). */
export function rustdeskLink(id: string): string {
  return `rustdesk://connection/new/${encodeURIComponent(id)}`;
}
