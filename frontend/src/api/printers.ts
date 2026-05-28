import api from "./http";

export type PrinterType = "laser" | "label";
export type ConnectionType = "ip" | "usb";

export interface Printer {
  id: string;
  printer_type: PrinterType;
  connection_type: ConnectionType;
  store_name: string;
  model: string;
  ip_address: string | null;
  mac_address: string | null;
  mac_status: string | null;
  host_pc: string | null;
  is_online: boolean | null;
  status: string | null;
  toner_black: number | null;
  toner_cyan: number | null;
  toner_magenta: number | null;
  toner_yellow: number | null;
  toner_black_name: string | null;
  toner_cyan_name: string | null;
  toner_magenta_name: string | null;
  toner_yellow_name: string | null;
  last_polled_at: string | null;
  created_at: string;
}

export interface PrintersResponse {
  data: Printer[];
  count: number;
}

export interface CartridgeStock {
  id: string;
  cartridge_name: string;
  toner_color: string | null;
  compatible_printer_models: string;
  printer_count: number;
  quantity_on_hand: number;
  minimum_stock: number;
  is_active: boolean;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface CartridgeStocksResponse {
  data: CartridgeStock[];
  count: number;
}

export interface CartridgeStockMovement {
  id: string;
  stock_id: string;
  delta: number;
  reason: string;
  note: string | null;
  created_by: string | null;
  created_at: string;
}

export interface CartridgeStockMovementsResponse {
  data: CartridgeStockMovement[];
  count: number;
}

export async function getPrinters(store_name?: string, printer_type: PrinterType = "laser") {
  const params: Record<string, string> = { printer_type };
  if (store_name) params.store_name = store_name;
  const { data } = await api.get<PrintersResponse>("/printers/", { params });
  return data;
}

export async function createPrinter(printer: {
  printer_type?: PrinterType;
  connection_type?: ConnectionType;
  store_name: string;
  model: string;
  ip_address?: string;
  snmp_community?: string;
  host_pc?: string;
  toner_black_name?: string;
  toner_cyan_name?: string;
  toner_magenta_name?: string;
  toner_yellow_name?: string;
}) {
  const { data } = await api.post<Printer>("/printers/", printer);
  return data;
}

export async function updatePrinter(id: string, printer: Partial<Printer>) {
  const { data } = await api.patch<Printer>(`/printers/${id}`, printer);
  return data;
}

export async function deletePrinter(id: string) {
  await api.delete(`/printers/${id}`);
}

export async function pollPrinter(id: string) {
  const { data } = await api.post<Printer>(`/printers/${id}/poll`);
  return data;
}

export async function pollAllPrinters(printer_type: PrinterType = "laser") {
  const { data } = await api.post<PrintersResponse>("/printers/poll-all", null, {
    params: { printer_type },
  });
  return data;
}

export async function getCartridgeStocks(search?: string) {
  const params: Record<string, string> = {};
  if (search) params.search = search;
  const { data } = await api.get<CartridgeStocksResponse>("/printers/cartridges", { params });
  return data;
}

export async function syncCartridgeStocks() {
  const { data } = await api.post<CartridgeStocksResponse>("/printers/cartridges/sync");
  return data;
}

export async function updateCartridgeStock(
  id: string,
  payload: { quantity_on_hand?: number; minimum_stock?: number; note?: string },
) {
  const { data } = await api.patch<CartridgeStock>(`/printers/cartridges/${id}`, payload);
  return data;
}

export async function issueCartridgeStock(id: string, payload: { quantity?: number; note?: string }) {
  const { data } = await api.post<CartridgeStock>(`/printers/cartridges/${id}/issue`, payload);
  return data;
}

export async function getCartridgeStockMovements(id: string) {
  const { data } = await api.get<CartridgeStockMovementsResponse>(`/printers/cartridges/${id}/movements`);
  return data;
}
