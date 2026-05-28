import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Shield, UserIcon, Pencil, Trash2, Search } from "lucide-react";
import {
  getUsers,
  createUser,
  updateUser,
  deleteUser,
  type User,
} from "../client";
import { useAuth } from "../auth";
import UserForm from "../components/UserForm";

export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();

  const [showForm, setShowForm] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: getUsers,
  });

  const extractError = (err: unknown): string => {
    if (err && typeof err === "object" && "response" in err) {
      const resp = (err as { response?: { data?: { detail?: string } } }).response;
      const detail = resp?.data?.detail;
      if (detail === "A user with this email already exists") return "Пользователь с таким email уже существует";
      if (detail) return detail;
    }
    return "Не удалось сохранить";
  };

  const createMut = useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      setFormError(null);
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setShowForm(false);
    },
    onError: (err) => setFormError(extractError(err)),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, ...rest }: { id: string } & Parameters<typeof updateUser>[1]) =>
      updateUser(id, rest),
    onSuccess: () => {
      setFormError(null);
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setEditingUser(null);
      setShowForm(false);
    },
    onError: (err) => setFormError(extractError(err)),
  });

  const deleteMut = useMutation({
    mutationFn: deleteUser,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const handleDelete = (user: User) => {
    if (user.id === currentUser?.id) return;
    if (confirm(`Удалить пользователя ${user.email}?`)) {
      deleteMut.mutate(user.id);
    }
  };

  const users = data?.data ?? [];
  const ONLINE_WINDOW_MS = 5 * 60_000;
  const parseServerDate = (value: string): Date => {
    // Backend may send naive ISO datetime (without timezone). Treat it as UTC.
    const hasTz = /(?:Z|[+\-]\d{2}:\d{2})$/.test(value);
    return new Date(hasTz ? value : `${value}Z`);
  };
  const isRecentlyOnline = (lastSeenAt: string | null): boolean => {
    if (!lastSeenAt) return false;
    const parsed = parseServerDate(lastSeenAt);
    const ts = parsed.getTime();
    if (Number.isNaN(ts)) return false;
    return Date.now() - ts <= ONLINE_WINDOW_MS;
  };
  const visibleUsers = users.filter((u) => {
    const haystack = `${u.full_name ?? ""} ${u.email}`.toLowerCase();
    return haystack.includes(search.trim().toLowerCase());
  });

  return (
    <div className="space-y-6">
      <div className="app-panel p-3">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="relative w-full md:max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="app-input w-full pl-10 pr-4 py-2 text-sm"
              placeholder="Поиск: пользователь, email"
            />
          </div>
          <button
            onClick={() => { setEditingUser(null); setFormError(null); setShowForm(true); }}
            className="app-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm transition"
          >
            <Plus className="h-4 w-4" />
            Создать
          </button>
        </div>
      </div>

      <div className="grid gap-4 grid-cols-2 sm:grid-cols-3">
        <div className="app-stat bg-gray-100 px-4 py-3">
          <div className="text-2xl font-bold text-gray-900">{users.length}</div>
          <div className="text-xs text-gray-500 mt-0.5">Всего</div>
        </div>
        <div className="app-stat bg-rose-50 px-4 py-3">
          <div className="text-2xl font-bold text-rose-700">{users.filter((u) => u.is_superuser).length}</div>
          <div className="text-xs text-gray-500 mt-0.5">Администраторы</div>
        </div>
        <div className="app-stat bg-emerald-50 px-4 py-3">
          <div className="text-2xl font-bold text-emerald-700">{users.filter((u) => u.is_active).length}</div>
          <div className="text-xs text-gray-500 mt-0.5">Активные</div>
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-rose-500 border-t-transparent" />
        </div>
      ) : visibleUsers.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          <p className="text-lg">Нет пользователей</p>
        </div>
      ) : (
        <div className="app-panel overflow-hidden app-compact-scroll">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Пользователь</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Онлайн</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {visibleUsers.map((u) => (
                <tr key={u.id} className="hover:bg-gray-50 transition">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className={`flex items-center justify-center h-8 w-8 rounded-full ${u.is_superuser ? "bg-rose-100" : "bg-gray-100"}`}>
                        {u.is_superuser ? (
                          <Shield className="h-4 w-4 text-rose-600" />
                        ) : (
                          <UserIcon className="h-4 w-4 text-gray-500" />
                        )}
                      </div>
                      <div>
                        <div className="text-sm font-medium text-gray-900 inline-flex items-center gap-1.5">
                          <span>{u.full_name || "—"}</span>
                          {u.is_superuser ? (
                            <span title="Администратор"><Shield className="h-3.5 w-3.5 text-rose-600" /></span>
                          ) : (
                            <span title="Пользователь"><UserIcon className="h-3.5 w-3.5 text-slate-500" /></span>
                          )}
                        </div>
                        <div className="text-xs text-gray-500">{u.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {u.is_active && isRecentlyOnline(u.last_seen_at) ? (
                      <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium bg-emerald-100 text-emerald-700">
                        Онлайн
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium bg-red-100 text-red-700">
                        Оффлайн
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => { setEditingUser(u); setFormError(null); setShowForm(true); }}
                        className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition"
                        title="Редактировать"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      {u.id !== currentUser?.id && (
                        <button
                          onClick={() => handleDelete(u)}
                          className="rounded-lg p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 transition"
                          title="Удалить"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <UserForm
          user={editingUser}
          loading={createMut.isPending || updateMut.isPending}
          error={formError}
          onClose={() => { setShowForm(false); setEditingUser(null); setFormError(null); }}
          onSave={(formData) => {
            setFormError(null);
            if (editingUser) {
              updateMut.mutate({ id: editingUser.id, ...formData });
            } else {
              createMut.mutate({ ...formData, password: formData.password! });
            }
          }}
        />
      )}
    </div>
  );
}
