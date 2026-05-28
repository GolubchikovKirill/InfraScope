import api from "./http";
import type { MediaPlayer } from "./mediaPlayers";
import type { Printer, PrinterType } from "./printers";
import type { NetworkSwitch } from "./switches";

export interface DiscoveredDevice {
  ip: string;
  mac: string | null;
  open_ports: number[];
  hostname: string | null;
  is_known: boolean;
  known_printer_id: string | null;
  ip_changed: boolean;
  old_ip: string | null;
}

export interface ScanProgress {
  status: "idle" | "running" | "done" | "error";
  scanned: number;
  total: number;
  found: number;
  message: string | null;
}

export interface ScanResultsResponse {
  progress: ScanProgress;
  devices: DiscoveredDevice[];
}

export interface SmartNetworkCandidate {
  ip: string;
  hostname: string | null;
  open_ports: number[];
  confidence: "high" | "medium" | "low" | string;
  reason: string;
}

export interface SmartNetworkSearchResponse {
  data: SmartNetworkCandidate[];
  count: number;
  used_subnet: string;
  used_ports: string;
}

export interface DiscoveredNetworkDevice {
  ip: string;
  mac: string | null;
  open_ports: number[];
  hostname: string | null;
  model_info: string | null;
  vendor: string | null;
  device_kind: string | null;
  is_known: boolean;
  known_device_id: string | null;
  ip_changed: boolean;
  old_ip: string | null;
}

export interface DiscoveryResultsResponse {
  progress: ScanProgress;
  devices: DiscoveredNetworkDevice[];
}

export async function startScan(subnet: string, ports: string = "9100,631,80,443") {
  const { data } = await api.post<ScanProgress>("/scanner/scan", { subnet, ports });
  return data;
}

export async function getScanStatus() {
  const { data } = await api.get<ScanProgress>("/scanner/status");
  return data;
}

export async function getScanResults() {
  const { data } = await api.get<ScanResultsResponse>("/scanner/results");
  return data;
}

export async function getScannerSettings() {
  const { data } = await api.get<{
    subnet: string;
    ports: string;
    dns_search_suffixes?: string;
    max_hosts: number;
    tcp_timeout: number;
    tcp_retries: number;
    tcp_concurrency: number;
  }>("/scanner/settings");
  return data;
}

export async function smartSearchComputersInNetwork(payload?: {
  subnet?: string;
  ports?: string;
  hostname_contains?: string;
  limit?: number;
}) {
  const { data } = await api.post<SmartNetworkSearchResponse>("/scanner/smart-search/computers", payload ?? {});
  return data;
}

export async function smartSearchCashRegistersInNetwork(payload?: {
  subnet?: string;
  ports?: string;
  hostname_contains?: string;
  limit?: number;
}) {
  const { data } = await api.post<SmartNetworkSearchResponse>("/scanner/smart-search/cash-registers", payload ?? {});
  return data;
}

export async function addDiscoveredPrinter(printer: {
  printer_type?: PrinterType;
  store_name: string;
  model: string;
  ip_address: string;
  snmp_community?: string;
}) {
  const { data } = await api.post<Printer>("/scanner/add", printer);
  return data;
}

export async function updatePrinterIp(printerId: string, newIp: string, newMac?: string) {
  const params: Record<string, string> = { new_ip: newIp };
  if (newMac) params.new_mac = newMac;
  const { data } = await api.post<Printer>(`/scanner/update-ip/${printerId}`, null, { params });
  return data;
}

export async function startIconbitDiscoveryScan(subnet: string, ports: string = "8081,80,443") {
  const { data } = await api.post<ScanProgress>("/media-players/discover/scan", { subnet, ports });
  return data;
}

export async function getIconbitDiscoveryResults() {
  const { data } = await api.get<DiscoveryResultsResponse>("/media-players/discover/results");
  return data;
}

export async function addDiscoveredIconbit(payload: {
  ip_address: string;
  name?: string;
  model?: string;
  mac_address?: string;
}) {
  const { data } = await api.post<MediaPlayer>("/media-players/discover/add", payload);
  return data;
}

export async function updateDiscoveredIconbitIp(playerId: string, newIp: string, newMac?: string) {
  const params: Record<string, string> = { new_ip: newIp };
  if (newMac) params.new_mac = newMac;
  const { data } = await api.post<MediaPlayer>(`/media-players/discover/update-ip/${playerId}`, null, { params });
  return data;
}

export async function startSwitchDiscoveryScan(subnet: string, ports: string = "22,80,443") {
  const { data } = await api.post<ScanProgress>("/switches/discover/scan", { subnet, ports });
  return data;
}

export async function getSwitchDiscoveryResults() {
  const { data } = await api.get<DiscoveryResultsResponse>("/switches/discover/results");
  return data;
}

export async function addDiscoveredSwitch(payload: {
  ip_address: string;
  name?: string;
  hostname?: string;
  vendor?: string;
}) {
  const { data } = await api.post<NetworkSwitch>("/switches/discover/add", payload);
  return data;
}

export async function updateDiscoveredSwitchIp(switchId: string, newIp: string) {
  const { data } = await api.post<NetworkSwitch>(`/switches/discover/update-ip/${switchId}`, null, {
    params: { new_ip: newIp },
  });
  return data;
}
