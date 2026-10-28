// The vault list: search, category filter, reveal / copy / edit / delete.
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Copy,
  ExternalLink,
  Eye,
  KeyRound,
  MonitorSmartphone,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import {
  CREDENTIAL_CATEGORIES,
  deleteCredential,
  getCredentials,
  revealCredential,
  type Credential,
  type CredentialCategory,
} from "../../client";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { useQueryParamState } from "../../hooks/useQueryParamState";
import { useRowFocus } from "../../hooks/useRowFocus";
import { useRemoteDeviceMap } from "../../hooks/useRemoteDeviceMap";
import { useConfirm } from "../../components/ConfirmDialog";
import { showToast } from "../../lib/toastBus";
import { relTime } from "../../lib/relTime";
import { deviceHrefForCredential, rowDomId, rustdeskHrefForHost } from "../../lib/deviceLinks";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  SectionCard,
} from "../../components/ui/AsyncState";
import { CATEGORY_LABEL, categoryTone, copyText } from "./shared";
import { RevealDialog } from "./RevealDialog";
import { CredentialFormModal } from "./CredentialFormModal";

export function VaultSection() {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [q, setQ] = useQueryParamState("q");
  const [focus] = useQueryParamState("focus");
  const debouncedQ = useDebouncedValue(q, 300);
  const [category, setCategory] = useState<"" | CredentialCategory>("");
  const [editing, setEditing] = useState<Credential | null>(null);
  const [creating, setCreating] = useState(false);
  const [reveal, setReveal] = useState<{
    title: string;
    secret: string;
    notes: string | null;
    deviceHref: string | null;
    connectHref: string | null;
  } | null>(null);
  const { map: remoteMap } = useRemoteDeviceMap();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["credentials", debouncedQ, category],
    queryFn: () =>
      getCredentials({
        q: debouncedQ || undefined,
        category: category || undefined,
      }),
    placeholderData: keepPreviousData,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["credentials"] });

  const revealMut = useMutation({
    mutationFn: (c: Credential) => revealCredential(c.id),
    onSuccess: (secret, c) =>
      setReveal({
        title: c.title,
        secret: secret.secret,
        notes: secret.notes,
        deviceHref: deviceHrefForCredential(c),
        connectHref: rustdeskHrefForHost(c.host, remoteMap),
      }),
    onError: () => showToast("Не удалось получить пароль", "error"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteCredential(id),
    onSuccess: (r) => {
      showToast(r.message, "success");
      invalidate();
    },
    onError: () => showToast("Не удалось удалить запись", "error"),
  });

  const rows = data?.data ?? [];
  useRowFocus(
    focus,
    rows.map((c) => ({ id: c.id, keys: [c.host, c.title] })),
  );

  return (
    <SectionCard className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-slate-900">
          <KeyRound className="h-4 w-4" />
          <h2 className="text-base font-semibold">Хранилище</h2>
          {data ? <span className="text-xs text-slate-400">{data.count}</span> : null}
        </div>
        <button
          onClick={() => setCreating(true)}
          className="app-btn-primary inline-flex items-center gap-2 px-3 py-2 text-sm"
        >
          <Plus className="h-4 w-4" />
          Добавить
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        <label className="relative flex-1 min-w-[200px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            className="app-input w-full py-2 pl-9 pr-3 text-sm"
            placeholder="Поиск по названию, хосту, логину, тегам"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        <select
          className="app-input py-2 px-3 text-sm"
          value={category}
          onChange={(e) => setCategory(e.target.value as "" | CredentialCategory)}
        >
          <option value="">Все категории</option>
          {CREDENTIAL_CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState text="Не удалось загрузить хранилище." />
      ) : rows.length === 0 ? (
        <EmptyState text="Записей нет. Добавьте первую учётную запись." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-[var(--app-panel-border)] text-left text-xs text-slate-500">
                <th className="py-2 pr-3 font-medium">Название</th>
                <th className="py-2 pr-3 font-medium">Категория</th>
                <th className="py-2 pr-3 font-medium">Логин</th>
                <th className="py-2 pr-3 font-medium">Хост / URL</th>
                <th className="py-2 pr-3 font-medium">Магазин</th>
                <th className="py-2 pr-3 font-medium">Изменено</th>
                <th className="py-2 pr-3" />
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const deviceHref = deviceHrefForCredential(c);
                const connectHref = rustdeskHrefForHost(c.host, remoteMap);
                return (
                <tr
                  key={c.id}
                  id={rowDomId(c.id)}
                  className="border-b border-[var(--app-panel-border)]/60 align-top"
                >
                  <td className="py-2 pr-3">
                    <div className="font-medium text-slate-800">{c.title}</div>
                    {c.tags ? (
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {c.tags.split(",").map((t) => (
                          <span key={t} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500">
                            {t.trim()}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </td>
                  <td className="py-2 pr-3">
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${categoryTone(c.category)}`}
                    >
                      {CATEGORY_LABEL[c.category] ?? c.category}
                    </span>
                  </td>
                  <td className="py-2 pr-3">
                    {c.username ? (
                      <button
                        className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900"
                        onClick={() => copyText(c.username!, "Логин")}
                        title="Скопировать логин"
                      >
                        {c.username}
                        <Copy className="h-3 w-3" />
                      </button>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-slate-600">
                    {c.url ? (
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[var(--brand)] hover:underline"
                        title="Открыть панель"
                      >
                        {c.host || c.url}
                      </a>
                    ) : (
                      c.host || <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-slate-600">
                    {c.location || <span className="text-slate-400">—</span>}
                  </td>
                  <td className="py-2 pr-3 text-xs text-slate-400">
                    {relTime(c.updated_at ?? c.created_at)}
                  </td>
                  <td className="py-2 pr-1">
                    <div className="flex items-center justify-end gap-1">
                      {connectHref && (
                        <a
                          href={connectHref}
                          className="rounded-lg p-1.5 text-[var(--brand)] hover:bg-slate-100"
                          title="Подключиться через RustDesk"
                        >
                          <MonitorSmartphone className="h-4 w-4" />
                        </a>
                      )}
                      {deviceHref && (
                        <Link
                          to={deviceHref}
                          className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
                          title="Открыть карточку устройства"
                        >
                          <ExternalLink className="h-4 w-4" />
                        </Link>
                      )}
                      <button
                        className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800 disabled:opacity-40"
                        title="Показать пароль"
                        disabled={!c.has_secret || revealMut.isPending}
                        onClick={() => revealMut.mutate(c)}
                      >
                        <Eye className="h-4 w-4" />
                      </button>
                      <button
                        className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
                        title="Редактировать"
                        onClick={() => setEditing(c)}
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button
                        className="rounded-lg p-1.5 text-rose-500 hover:bg-rose-50 hover:text-rose-700"
                        title="Удалить"
                        onClick={async () => {
                          const ok = await confirm(`Удалить запись «${c.title}»?`, { danger: true, confirmText: "Удалить" });
                          if (ok) deleteMut.mutate(c.id);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {(creating || editing) && (
        <CredentialFormModal
          initial={editing}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={() => {
            setCreating(false);
            setEditing(null);
            invalidate();
          }}
        />
      )}
      {reveal && <RevealDialog {...reveal} onClose={() => setReveal(null)} />}
    </SectionCard>
  );
}
