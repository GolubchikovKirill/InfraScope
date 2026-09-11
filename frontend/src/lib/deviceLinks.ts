import type { Credential, CredentialCategory, RemoteDevice } from "../client";
import { rustdeskLink } from "../api/remoteAccess";

/** Where a credential's category sends you in the fleet nav. Categories with
 *  no matching inventory section (server/service/website/email/other) stay
 *  null - there is nowhere to "open the device". */
export const CATEGORY_TO_ROUTE: Partial<Record<CredentialCategory, string>> = {
  switch: "/switches",
  printer: "/printers",
  cash_register: "/cash-registers",
  computer: "/computers",
  media_player: "/media-players",
  camera: "/cameras",
};

/** Loose match key for a hostname/IP/URL so "VNA-KKM-1506", " vna-kkm-1506 "
 *  and "https://VNA-KKM-1506/" all line up. Credential.host is free text -
 *  operators paste whatever they have on hand. */
export function normalizeHostKey(value: string | null | undefined): string {
  if (!value) return "";
  let s = value.trim().toLowerCase();
  if (!s) return "";
  s = s.replace(/^[a-z][a-z0-9+.-]*:\/\//, ""); // strip a leading scheme://
  s = s.split(/[/?#]/, 1)[0]; // drop path/query/fragment
  s = s.split(":", 1)[0]; // drop a trailing :port
  return s;
}

/** DOM id for a list row, keyed by its own identity string (hostname, name, …). */
export function rowDomId(identity: string): string {
  return `row-${normalizeHostKey(identity) || identity}`;
}

/** Deep link from a credential row to its device's fleet page, pre-filtered
 *  and flagged for the highlight-on-arrival effect (see useRowFocus). Null
 *  when the category has no fleet section or the record has no host. */
export function deviceHrefForCredential(credential: Pick<Credential, "category" | "host">): string | null {
  const route = CATEGORY_TO_ROUTE[credential.category];
  const host = credential.host?.trim();
  if (!route || !host) return null;
  const q = encodeURIComponent(host);
  return `${route}?q=${q}&focus=${q}`;
}

/** Deep link from a device row back to the vault, pre-filtered to that host. */
export function credentialsHref(identity: string): string {
  return `/credentials?q=${encodeURIComponent(identity)}`;
}

/** Finds the managed RustDesk endpoint for a free-text host, if any. The map
 *  from useRemoteDeviceMap is keyed by exact hostname; credential.host may
 *  differ in case/whitespace, so compare normalized. */
export function matchRemoteDevice(
  host: string | null | undefined,
  remoteMap: Map<string, RemoteDevice>,
): RemoteDevice | null {
  const key = normalizeHostKey(host);
  if (!key) return null;
  for (const device of remoteMap.values()) {
    if (normalizeHostKey(device.hostname) === key) return device;
  }
  return null;
}

/** rustdesk:// link for a free-text host, if it resolves to a managed device. */
export function rustdeskHrefForHost(
  host: string | null | undefined,
  remoteMap: Map<string, RemoteDevice>,
): string | null {
  const device = matchRemoteDevice(host, remoteMap);
  if (!device) return null;
  return rustdeskLink(device.rustdesk_id ?? device.hostname);
}
