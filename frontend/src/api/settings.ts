import api from "./http";

export interface GeneralSettings {
  dns_search_suffixes: string;
}

export async function getGeneralSettings() {
  const { data } = await api.get<GeneralSettings>("/app-settings/general");
  return data;
}

export async function updateGeneralSettings(payload: Partial<GeneralSettings>) {
  const { data } = await api.patch<GeneralSettings>("/app-settings/general", payload);
  return data;
}
