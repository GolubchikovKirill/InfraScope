import api from "./http";

export type SourceKind = "cash_register" | "computer" | "media_player";

/** What the endpoint's own rollout script reported. "stale" is InfraScope's
 *  own marker (set locally, never sent by the script) - see Readiness. */
export type DeployState = "unknown" | "pending" | "installed" | "configured" | "failed" | "stale";

/** "client" = store kiosk: hidden, AppLocker blocks the employee from opening
 *  RustDesk themselves, inbound-only. "admin" = an engineer's own machine:
 *  full normal RustDesk, visible, they can launch it and connect out. */
export type DeployProfile = "client" | "admin";

/** Single chip for the device grid: can an engineer connect to this right now? */
export type Readiness =
  | "ready" // config applied AND the console sees the client
  | "installed_offline" // rolled out, but the machine is not reachable
  | "deploying" // waiting for the endpoint to run the bootstrap
  | "stale" // was configured, but the desired config changed since (redeploy needed)
  | "failed"
  | "not_deployed";

export interface RemoteDevice {
  id: string;
  hostname: string;
  location: string | null;
  source_kind: SourceKind;
  /** Role token read off the hostname (VNA-KKM-1506 -> "KKM"), same as the
   *  extra tag pushed into the shared address book. Null if the hostname
   *  doesn't fit the `<SITE>-<TYPE>-<NUM>` convention. */
  type_tag: string | null;
  computer_id: string | null;
  media_player_id: string | null;
  cash_register_id: string | null;
  rustdesk_id: string | null;
  has_password: boolean;
  password_rotated_at: string | null;
  /** "client" (store kiosk - hidden, AppLocker-blocked) or "admin" (an
   *  engineer's own workstation - full normal RustDesk). Sets the three
   *  fields below together; see setDeviceProfile. */
  deploy_profile: DeployProfile;
  desired_hidden: boolean;
  desired_block_outgoing: boolean;
  desired_unattended: boolean;
  managed: boolean;
  in_address_book: boolean;
  ab_password_pushed: boolean;
  deploy_state: DeployState;
  deploy_detail: string | null;
  deploy_requested_at: string | null;
  deploy_reported_at: string | null;
  readiness: Readiness;
  installed_version: string | null;
  os_edition: string | null; // raw registry EditionID, self-reported by the endpoint
  os_caption: string | null; // e.g. "Windows 10 Pro"
  applocker_supported: boolean | null; // null until the machine has reported
  /** true only when block_outgoing was requested AND we know it silently did
   *  not apply (Windows Home has no AppLocker) - never true while unknown. */
  applocker_mismatch: boolean;
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

/** Sets desired_hidden/desired_block_outgoing/desired_unattended together
 *  from a named preset, instead of getting all three right by hand. */
export async function setDeviceProfile(id: string, profile: DeployProfile) {
  const { data } = await api.post<RemoteDevice>(`/remote-access/devices/${id}/profile`, { profile });
  return data;
}

/** Create/link a device row and stamp its desired RustDesk id + password.
 *  Records config only - it reaches the machine on the next rollout run. */
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

/** Config for an offline KSC package (a machine with no network path back here). */
export async function getDevicePackage(id: string) {
  const { data } = await api.get<PackageConfig>(`/remote-access/devices/${id}/package`);
  return data;
}

export async function syncRemoteAccess() {
  const { data } = await api.post<{ message: string }>("/remote-access/sync");
  return data;
}

// --------------------------------------------------------------------------- //
// rollout                                                                     //
// --------------------------------------------------------------------------- //
export interface DeployCommand {
  /** The one line to paste into a KSC "run script" task, GPO, or schtasks. */
  command: string;
  bootstrap_url: string;
  installer_filename: string;
  installer_version: string;
  /** false when RUSTDESK_DEPLOY_TOKEN / RUSTDESK_PUBLIC_URL are unset on the server */
  configured: boolean;
}

export async function getDeployCommand() {
  const { data } = await api.get<DeployCommand>("/remote-access/deploy/command");
  return data;
}

/** Mark a device as awaiting rollout. InfraScope never remote-executes: the
 *  machine still has to run the bootstrap via KSC / GPO / schtasks. */
export async function requestDeploy(id: string) {
  const { data } = await api.post<RemoteDevice>(`/remote-access/devices/${id}/deploy`);
  return data;
}

// --------------------------------------------------------------------------- //
// shared address book                                                         //
// --------------------------------------------------------------------------- //
export interface AddressBookStatus {
  name: string;
  collection_id: number;
  owner_user_id: number;
  entries: number;
  shared_with_group: string;
  accounts: number;
}

export async function getAddressBookStatus() {
  const { data } = await api.get<AddressBookStatus>("/remote-access/address-book/status");
  return data;
}

/** Push devices into the shared console book, passwords included. */
export async function syncAddressBook(payload?: {
  device_ids?: string[];
  location?: string;
  source_kind?: SourceKind;
}) {
  const { data } = await api.post<{ message: string }>("/remote-access/address-book/sync", payload ?? {});
  return data;
}

// --------------------------------------------------------------------------- //
// console accounts                                                            //
// --------------------------------------------------------------------------- //
export interface ConsoleAccount {
  id: string;
  username: string;
  console_user_id: number | null;
  display_name: string | null;
  email: string | null;
  is_admin: boolean;
  infrascope_user_id: string | null;
  active: boolean;
  book_shared: boolean;
  last_synced_at: string | null;
  created_at: string;
}

export interface ConsoleAccountsResponse {
  data: ConsoleAccount[];
  count: number;
}

/** Create/reset response. `password` is shown once and stored nowhere. */
export interface ConsoleAccountSecret {
  account: ConsoleAccount;
  password: string;
  note: string;
}

export async function getConsoleAccounts() {
  const { data } = await api.get<ConsoleAccountsResponse>("/remote-access/accounts");
  return data;
}

export async function createConsoleAccount(payload: {
  username: string;
  display_name?: string;
  email?: string;
  is_admin?: boolean;
  password?: string;
}) {
  const { data } = await api.post<ConsoleAccountSecret>("/remote-access/accounts", payload);
  return data;
}

export async function resetConsoleAccountPassword(id: string, password?: string) {
  const { data } = await api.post<ConsoleAccountSecret>(
    `/remote-access/accounts/${id}/reset-password`,
    { password },
  );
  return data;
}

/** Disable rather than delete: the console refuses to drop its last admin. */
export async function setConsoleAccountActive(id: string, active: boolean) {
  const { data } = await api.post<ConsoleAccount>(`/remote-access/accounts/${id}/active`, null, {
    params: { active },
  });
  return data;
}

export async function syncConsoleAccounts() {
  const { data } = await api.post<{ message: string }>("/remote-access/accounts/sync");
  return data;
}

/** Mirror of service._hostname_to_rid: RustDesk custom IDs allow only [A-Za-z0-9_]. */
export function hostnameToRid(hostname: string): string {
  return Array.from(hostname)
    .map((c) => (/[A-Za-z0-9]/.test(c) ? c : "_"))
    .join("")
    .slice(0, 32);
}

// --------------------------------------------------------------------------- //
// console passthrough                                                         //
// --------------------------------------------------------------------------- //
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

/** The service account's *personal* book. The fleet lives in the shared book -
 *  see getAddressBookStatus(). */
export async function getConsoleAddressBook() {
  const { data } = await api.get<ConsoleAddressBookEntry[]>("/remote-access/console/address-book");
  return data;
}

export interface ConsoleUser {
  id?: number;
  name?: string;
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
