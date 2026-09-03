import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookUser, Copy, KeyRound, Plus, RefreshCw, UserCheck, UserX, X } from "lucide-react";
import {
  createConsoleAccount,
  getAddressBookStatus,
  getConsoleAccounts,
  resetConsoleAccountPassword,
  setConsoleAccountActive,
  syncConsoleAccounts,
  type ConsoleAccount,
  type ConsoleAccountSecret,
} from "../client";
import { useConfirm } from "./ConfirmDialog";
import { relTime } from "../lib/relTime";
import { showToast } from "../lib/toastBus";
import { Button } from "./ui/Button";

const USERNAME_RE = /^[A-Za-z0-9._-]{2,32}$/;

/** Engineer logins for the self-hosted RustDesk console, and the state of the
 *  shared address book every one of them joins on creation. Devices live on
 *  their own tab - this one is entirely about who can connect. */
export default function ConsoleAccountsPanel({ isSuperuser }: { isSuperuser: boolean }) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [createOpen, setCreateOpen] = useState(false);
  const [secret, setSecret] = useState<ConsoleAccountSecret | null>(null);

  const accounts = useQuery({
    queryKey: ["remote-access", "accounts"],
    queryFn: getConsoleAccounts,
    refetchInterval: 60000,
  });
  const bookStatus = useQuery({
    queryKey: ["remote-access", "address-book-status"],
    queryFn: getAddressBookStatus,
    retry: false,
    refetchInterval: 60000,
  });

  const invalidateAccounts = () => qc.invalidateQueries({ queryKey: ["remote-access", "accounts"] });

  const syncMut = useMutation({
    mutationFn: syncConsoleAccounts,
    onSuccess: (r) => {
      showToast(r.message, "success");
      invalidateAccounts();
    },
    onError: () => showToast("Не удалось синхронизировать учётки", "error"),
  });

  const activeMut = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => setConsoleAccountActive(id, active),
    onSuccess: (_r, vars) => {
      showToast(vars.active ? "Учётка включена" : "Учётка отключена", "success");
      invalidateAccounts();
    },
    onError: () => showToast("Не удалось изменить учётку", "error"),
  });

  const resetMut = useMutation({
    mutationFn: (id: string) => resetConsoleAccountPassword(id),
    onSuccess: (r) => {
      setSecret(r);
      invalidateAccounts();
    },
    onError: () => showToast("Не удалось сбросить пароль", "error"),
  });

  const toggleActive = async (a: ConsoleAccount) => {
    if (a.active) {
      const ok = await confirm(
        `Отключить учётку «${a.username}» в консоли RustDesk? Инженер потеряет доступ к парку.`,
        { danger: true, confirmText: "Отключить" },
      );
      if (!ok) return;
    }
    activeMut.mutate({ id: a.id, active: !a.active });
  };

  const rows = accounts.data?.data ?? [];

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="app-stat px-4 py-3">
          <div className="text-2xl font-bold text-gray-900">{rows.filter((a) => a.active).length}</div>
          <div className="mt-0.5 text-xs text-gray-500">Активных учёток</div>
        </div>
        <div className="app-stat px-4 py-3">
          <div className="text-2xl font-bold text-gray-900">{bookStatus.data?.entries ?? "—"}</div>
          <div className="mt-0.5 text-xs text-gray-500">
            Устройств в книге «{bookStatus.data?.name ?? "InfraScope"}»
          </div>
        </div>
        <div className="app-stat px-4 py-3">
          <div className="flex items-center gap-1.5 text-sm font-medium text-gray-900">
            <BookUser className="h-4 w-4 text-[var(--brand)]" />
            {bookStatus.data?.shared_with_group ?? "—"}
          </div>
          <div className="mt-0.5 text-xs text-gray-500">
            Книга расшарена на эту группу — новый инженер получает парк автоматически
          </div>
        </div>
      </div>

      {bookStatus.isError && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
          Консоль RustDesk не подключена — состояние общей книги недоступно. Укажите{" "}
          <code className="app-mono">RUSTDESK_API_TOKEN</code> в <code className="app-mono">.env</code> сервера.
        </div>
      )}

      <div className="app-panel overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-slate-50/70 px-4 py-3">
          <div className="text-sm font-semibold text-slate-700">Учётки инженеров</div>
          <div className="ml-auto flex gap-2">
            <Button variant="secondary" onClick={() => syncMut.mutate()} disabled={syncMut.isPending}>
              <RefreshCw className={`mr-1 h-4 w-4 ${syncMut.isPending ? "animate-spin" : ""}`} />
              Синхронизировать
            </Button>
            {isSuperuser && (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="mr-1 h-4 w-4" />
                Добавить
              </Button>
            )}
          </div>
        </div>

        <div className="overflow-x-auto app-compact-scroll">
          <table className="app-table min-w-full">
            <thead>
              <tr>
                <th>Логин</th>
                <th>Имя</th>
                <th>Роль</th>
                <th>Книга адресов</th>
                <th>Статус</th>
                <th className="text-right">Действия</th>
              </tr>
            </thead>
            <tbody>
              {accounts.isLoading && (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-gray-400">
                    Загрузка…
                  </td>
                </tr>
              )}
              {rows.map((a) => (
                <tr key={a.id}>
                  <td className="app-mono text-sm text-slate-800">{a.username}</td>
                  <td className="text-sm text-slate-600">{a.display_name || a.email || "—"}</td>
                  <td>
                    {a.is_admin ? (
                      <span className="inline-flex items-center rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700">
                        admin
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">инженер</span>
                    )}
                  </td>
                  <td className="text-xs">
                    {a.book_shared ? (
                      <span className="text-emerald-600">видит парк</span>
                    ) : (
                      <span className="text-gray-400">не расшарена</span>
                    )}
                  </td>
                  <td>
                    {a.active ? (
                      <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
                        <UserCheck className="h-3.5 w-3.5" /> активна
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs text-gray-400">
                        <UserX className="h-3.5 w-3.5" /> отключена
                      </span>
                    )}
                    {a.last_synced_at && (
                      <div className="text-[11px] text-gray-400">синхр. {relTime(a.last_synced_at)}</div>
                    )}
                  </td>
                  <td>
                    {isSuperuser && (
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="secondary"
                          size="sm"
                          className="!px-2"
                          title="Сбросить пароль"
                          disabled={resetMut.isPending || !a.console_user_id}
                          onClick={() => resetMut.mutate(a.id)}
                        >
                          <KeyRound className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          className="!px-2"
                          title={a.active ? "Отключить" : "Включить"}
                          disabled={activeMut.isPending || !a.console_user_id}
                          onClick={() => toggleActive(a)}
                        >
                          {a.active ? <UserX className="h-3.5 w-3.5" /> : <UserCheck className="h-3.5 w-3.5" />}
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {!accounts.isLoading && rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-gray-400">
                    Учёток пока нет. Нажмите «Добавить» или «Синхронизировать», если они уже
                    заведены в консоли.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {createOpen && (
        <CreateAccountDialog
          onClose={() => setCreateOpen(false)}
          onCreated={(r) => {
            setCreateOpen(false);
            setSecret(r);
            invalidateAccounts();
          }}
        />
      )}

      {secret && <AccountSecretDialog secret={secret} onClose={() => setSecret(null)} />}
    </div>
  );
}

function CreateAccountDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (secret: ConsoleAccountSecret) => void;
}) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [password, setPassword] = useState("");

  const createMut = useMutation({
    mutationFn: (payload: Parameters<typeof createConsoleAccount>[0]) => createConsoleAccount(payload),
    onSuccess: onCreated,
    onError: () => showToast("Не удалось создать учётку", "error"),
  });

  const usernameValid = USERNAME_RE.test(username.trim());

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
      <div className="app-panel w-full max-w-md space-y-4 p-5">
        <div className="flex items-start justify-between">
          <h2 className="text-base font-semibold text-slate-900">Новая учётка RustDesk</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X className="h-5 w-5" />
          </button>
        </div>
        <p className="text-xs text-slate-500">
          Учётка сразу попадёт в группу, которой расшарена общая книга адресов — инженер
          увидит весь управляемый парк при первом входе в клиент RustDesk.
        </p>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Логин</span>
          <input
            className="app-input w-full px-3 py-2 text-sm"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="ivanov"
            autoFocus
          />
          {username && !usernameValid && (
            <span className="mt-1 block text-xs text-rose-600">
              2–32 символа: латиница, цифры, точка, дефис, подчёркивание
            </span>
          )}
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Имя (необязательно)</span>
          <input
            className="app-input w-full px-3 py-2 text-sm"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Иван Иванов"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Email (необязательно)</span>
          <input
            className="app-input w-full px-3 py-2 text-sm"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="ivanov@company.ru"
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">Пароль (пусто — сгенерировать)</span>
          <input
            className="app-input w-full px-3 py-2 text-sm"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="text"
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={isAdmin}
            onChange={(e) => setIsAdmin(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300"
          />
          Администратор консоли (полные права, не только доступ к парку)
        </label>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="app-btn-secondary px-4 py-2 text-sm">
            Отмена
          </button>
          <button
            onClick={() =>
              createMut.mutate({
                username: username.trim(),
                display_name: displayName.trim() || undefined,
                email: email.trim() || undefined,
                is_admin: isAdmin,
                password: password.trim() || undefined,
              })
            }
            disabled={!usernameValid || createMut.isPending}
            className="app-btn-primary px-4 py-2 text-sm disabled:opacity-50"
          >
            Создать
          </button>
        </div>
      </div>
    </div>
  );
}

function AccountSecretDialog({ secret, onClose }: { secret: ConsoleAccountSecret; onClose: () => void }) {
  const copy = () =>
    navigator.clipboard?.writeText(secret.password).then(
      () => showToast("Пароль скопирован", "success"),
      () => showToast("Не удалось скопировать", "error"),
    );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
      <div className="app-panel w-full max-w-sm space-y-4 p-5">
        <div className="flex items-start justify-between">
          <h2 className="text-base font-semibold text-slate-900">Пароль · {secret.account.username}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {secret.note}
        </div>
        <div className="flex items-center gap-2">
          <code className="app-mono flex-1 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-800">
            {secret.password}
          </code>
          <button
            onClick={copy}
            className="app-btn-secondary inline-flex items-center gap-1.5 px-3 py-2 text-sm"
          >
            <Copy className="h-3.5 w-3.5" />
            Копировать
          </button>
        </div>
        <div className="flex justify-end">
          <button onClick={onClose} className="app-btn-primary px-4 py-2 text-sm">
            Готово
          </button>
        </div>
      </div>
    </div>
  );
}
