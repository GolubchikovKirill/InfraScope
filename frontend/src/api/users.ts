import api from "./http";

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  last_seen_at: string | null;
  created_at: string;
}

export interface UsersResponse {
  data: User[];
  count: number;
}

export async function getUsers() {
  const { data } = await api.get<UsersResponse>("/users/");
  return data;
}

export async function createUser(user: {
  email: string;
  password: string;
  full_name?: string;
  is_superuser?: boolean;
}) {
  const { data } = await api.post<User>("/users/", user);
  return data;
}

export async function updateUser(
  id: string,
  user: { email?: string; password?: string; full_name?: string; is_superuser?: boolean; is_active?: boolean },
) {
  const { data } = await api.patch<User>(`/users/${id}`, user);
  return data;
}

export async function deleteUser(id: string) {
  await api.delete(`/users/${id}`);
}
