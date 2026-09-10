import api from "./http";

export type CredentialCategory =
  | "switch"
  | "printer"
  | "cash_register"
  | "computer"
  | "media_player"
  | "camera"
  | "server"
  | "service"
  | "website"
  | "other";

export const CREDENTIAL_CATEGORIES: { value: CredentialCategory; label: string }[] = [
  { value: "switch", label: "Свитч" },
  { value: "printer", label: "Принтер" },
  { value: "cash_register", label: "Касса" },
  { value: "computer", label: "Компьютер" },
  { value: "media_player", label: "Медиаплеер" },
  { value: "camera", label: "Камера" },
  { value: "server", label: "Сервер" },
  { value: "service", label: "Сервис" },
  { value: "website", label: "Веб-панель" },
  { value: "other", label: "Прочее" },
];

export interface Credential {
  id: string;
  title: string;
  category: CredentialCategory;
  username: string | null;
  /** The plaintext secret is never in this payload - use revealCredential(). */
  has_secret: boolean;
  host: string | null;
  location: string | null;
  url: string | null;
  notes: string | null;
  tags: string | null;
  secret_rotated_at: string | null;
  created_by_id: string | null;
  updated_by_id: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface CredentialsResponse {
  data: Credential[];
  count: number;
}

export interface CredentialInput {
  title: string;
  category: CredentialCategory;
  username?: string | null;
  /** Required on create; omit or leave blank on update to keep the stored one. */
  secret?: string;
  host?: string | null;
  location?: string | null;
  url?: string | null;
  notes?: string | null;
  tags?: string | null;
}

export interface CredentialSecret {
  id: string;
  secret: string;
  notes: string | null;
}

export interface PasswordGenParams {
  length: number;
  uppercase: boolean;
  lowercase: boolean;
  digits: boolean;
  symbols: boolean;
  exclude_ambiguous: boolean;
  exclude_chars: string;
  min_of_each: boolean;
}

export interface PasswordGenResult {
  password: string;
  entropy_bits: number;
}

export async function getCredentials(params?: {
  q?: string;
  category?: CredentialCategory;
  location?: string;
}) {
  const { data } = await api.get<CredentialsResponse>("/credentials", { params });
  return data;
}

export async function getCredential(id: string) {
  const { data } = await api.get<Credential>(`/credentials/${id}`);
  return data;
}

export async function createCredential(payload: CredentialInput) {
  const { data } = await api.post<Credential>("/credentials", payload);
  return data;
}

export async function updateCredential(id: string, payload: Partial<CredentialInput>) {
  const { data } = await api.patch<Credential>(`/credentials/${id}`, payload);
  return data;
}

export async function deleteCredential(id: string) {
  const { data } = await api.delete<{ message: string }>(`/credentials/${id}`);
  return data;
}

/** POST (not GET): the server writes an audit-log entry for every reveal. */
export async function revealCredential(id: string) {
  const { data } = await api.post<CredentialSecret>(`/credentials/${id}/reveal`);
  return data;
}

/** Server-side generator - the source of truth. The UI also has a local mirror
 *  (lib/passwordGen) for instant slider/checkbox feedback. */
export async function generatePassword(params: PasswordGenParams) {
  const { data } = await api.post<PasswordGenResult>("/credentials/generate-password", params);
  return data;
}
