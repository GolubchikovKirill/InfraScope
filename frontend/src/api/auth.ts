import api from "./http";
import axios from "axios";

export interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  is_superuser: boolean;
}

export async function login(email: string, password: string) {
  const params = new URLSearchParams();
  params.append("username", email);
  params.append("password", password);
  const { data } = await api.post<{ access_token: string }>("/auth/login", params, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return data;
}

export async function logout() {
  try {
    await api.post("/auth/logout");
  } catch {
    // ignore errors on logout
  }
}

export async function getMe() {
  try {
    const { data } = await api.get<AuthUser>("/auth/me");
    return data;
  } catch (error) {
    // Compatibility path for older backend versions.
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      const { data } = await api.post<AuthUser>("/auth/test-token");
      return data;
    }
    throw error;
  }
}
