import api from "./http";

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
  desired_hidden: boolean;
  desired_block_outgoing: boolean;
  desired_unattended: boolean;
  managed: boolean;
  in_address_book: boolean;
  installed_version: string | null;
  online: boolean | null;
  logged_in_user: string | null;
  last_ip: string | null;
  last_seen_at: string | null;
  host_online: boolean | null;
  host_last_seen_at: string | null;
  created_at: string;
}

export interface RemoteDevicesResponse {
  data: RemoteDevice[];
  count: number;
}

export async function getRemoteDevices(params?: {
  q?: string;
  location?: string;
  source_kind?: SourceKind;
  hostnames?: string;
}) {
  const { data } = await api.get<RemoteDevicesResponse>("/remote-access/devices", { params });
  return data;
}

export async function updateRemoteDevice(id: string, payload: Partial<RemoteDevice>) {
  const { data } = await api.patch<RemoteDevice>(`/remote-access/devices/${id}`, payload);
  return data;
}

/** Create/link a device row and stamp its desired RustDesk id + password.
 *  Records config only - the client itself is rolled out via KSC. */
export async function ensureRustDeskDevice(payload: {
  hostname: string;
  rustdesk_id?: string;
  permanent_password?: string;
}) {
  const { data } = await api.post<RemoteDevice>("/remote-access/devices/ensure", payload);
  return data;
}

export async function rotateRemotePassword(id: string) {
  const { data } = await api.post<RemoteDevice>(`/remote-access/devices/${id}/rotate-password`);
  return data;
}

export interface PackageConfig {
  hostname: string;
  rustdesk_id: string;
  id_server: string;
  relay_server: string;
  api_server: string;
  key: string;
  permanent_password: string;
  installer_version: string;
  hidden: boolean;
  block_outgoing: boolean;
  unattended: boolean;
}

export async function getDevicePackage(id: string) {
  const { data } = await api.get<PackageConfig>(`/remote-access/devices/${id}/package`);
  return data;
}

export async function syncRemoteAccess() {
  const { data } = await api.post<{ message: string }>("/remote-access/sync");
  return data;
}

export async function syncAddressBook(payload?: {
  device_ids?: string[];
  location?: string;
  source_kind?: SourceKind;
}) {
  const { data } = await api.post<{ message: string }>("/remote-access/address-book/sync", payload ?? {});
  return data;
}

/** Mirror of service._hostname_to_rid: RustDesk custom IDs allow only [A-Za-z0-9_]. */
export function hostnameToRid(hostname: string): string {
  return Array.from(hostname)
    .map((c) => (/[A-Za-z0-9]/.test(c) ? c : "_"))
    .join("")
    .slice(0, 32);
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
