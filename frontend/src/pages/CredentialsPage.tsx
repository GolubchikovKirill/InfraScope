import { useEffect, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Copy,
  Eye,
  EyeOff,
  KeyRound,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Wand2,
  X,
} from "lucide-react";
import {
  CREDENTIAL_CATEGORIES,
  createCredential,
  deleteCredential,
  getCredentials,
  revealCredential,
  updateCredential,
  type Credential,
  type CredentialCategory,
  type CredentialInput,
} from "../client";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useConfirm } from "../components/ConfirmDialog";
import { showToast } from "../lib/toastBus";
import { relTime } from "../lib/relTime";
import { EmptyState, ErrorState, LoadingState, SectionCard } from "../components/ui/AsyncState";
import { DEFAULT_PARAMS, generatePasswordLocal, type LocalPasswordResult } from "../lib/passwordGen";
import type { PasswordGenParams } from "../api/credentials";

const CATEGORY_LABEL: Record<CredentialCategory, string> = Object.fromEntries(
  CREDENTIAL_CATEGORIES.map((c) => [c.value, c.label]),
) as Record<CredentialCategory, string>;

function categoryTone(category: CredentialCategory): string {
  const map: Partial<Record<CredentialCategory, string>> = {
    switch: "bg-sky-100 text-sky-700",
    printer: "bg-slate-100 text-slate-600",
    cash_register: "bg-violet-100 text-violet-700",
    computer: "bg-indigo-100 text-indigo-700",
    media_player: "bg-amber-100 text-amber-800",
    camera: "bg-teal-100 text-teal-700",
    server: "bg-rose-100 text-rose-700",
    service: "bg-emerald-100 text-emerald-700",
    website: "bg-blue-100 text-blue-700",
    email: "bg-orange-100 text-orange-700",
  };
  return map[category] ?? "bg-slate-100 text-slate-600";
}

async function copyText(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(`${label} скопирован`, "success");
  } catch {
    showToast("Не удалось скопировать", "error");
  }
}

export default function CredentialsPage() {
  return (
    <div className="space-y-6">
      <VaultSection />
      <GeneratorSection />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// vault                                                                      //
// --------------------------------------------------------------------------- //
function VaultSection() {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [q, setQ] = useState("");
  const debouncedQ = useDebouncedValue(q, 300);
  const [category, setCategory] = useState<"" | CredentialCategory>("");
  const [editing, setEditing] = useState<Credential | null>(null);
  const [creating, setCreating] = useState(false);
  const [reveal, setReveal] = useState<{ title: string; secret: string; notes: string | null } | null>(null);

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
    onSuccess: (secret, c) => setReveal({ title: c.title, secret: secret.secret, notes: secret.notes }),
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

  return (
    <SectionCard className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
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
              {rows.map((c) => (
                <tr key={c.id} className="border-b border-[var(--app-panel-border)]/60 align-top">
                  <td className="py-2 pr-3">
                    <div className="font-medium text-slate-800 dark:text-slate-100">{c.title}</div>
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
                        className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900 dark:text-slate-300"
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
                  <td className="py-2 pr-3 text-slate-600 dark:text-slate-300">
                    {c.url ? (
                      <a href={c.url} target="_blank" rel="noreferrer" className="text-[var(--brand)] hover:underline">
                        {c.host || c.url}
                      </a>
                    ) : (
                      c.host || <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-slate-600 dark:text-slate-300">
                    {c.location || <span className="text-slate-400">—</span>}
                  </td>
                  <td className="py-2 pr-3 text-xs text-slate-400">
                    {relTime(c.updated_at ?? c.created_at)}
                  </td>
                  <td className="py-2 pr-1">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800 disabled:opacity-40 dark:hover:bg-slate-800"
                        title="Показать пароль"
                        disabled={!c.has_secret || revealMut.isPending}
                        onClick={() => revealMut.mutate(c)}
                      >
                        <Eye className="h-4 w-4" />
                      </button>
                      <button
                        className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:hover:bg-slate-800"
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
              ))}
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

// --------------------------------------------------------------------------- //
// reveal dialog                                                              //
// --------------------------------------------------------------------------- //
function RevealDialog({
  title,
  secret,
  notes,
  onClose,
}: {
  title: string;
  secret: string;
  notes: string | null;
  onClose: () => void;
}) {
  const [shown, setShown] = useState(false);

  // auto-close so a revealed secret is not left on screen
  useEffect(() => {
    const t = setTimeout(onClose, 30_000);
    return () => clearTimeout(t);
  }, [onClose]);

  return (
    <Modal onClose={onClose} title={title}>
      <div className="space-y-3">
        <div>
          <div className="mb-1 text-xs text-slate-500">Пароль</div>
          <div className="flex items-center gap-2">
            <code className="flex-1 break-all rounded-lg bg-slate-100 px-3 py-2 font-mono text-sm dark:bg-slate-800">
              {shown ? secret : "•".repeat(Math.min(secret.length, 24))}
            </code>
            <button
              className="app-btn-secondary rounded-lg p-2"
              onClick={() => setShown((s) => !s)}
              title={shown ? "Скрыть" : "Показать"}
            >
              {shown ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
            <button className="app-btn-secondary rounded-lg p-2" onClick={() => copyText(secret, "Пароль")} title="Скопировать">
              <Copy className="h-4 w-4" />
            </button>
          </div>
        </div>
        {notes ? (
          <div>
            <div className="mb-1 text-xs text-slate-500">Заметки</div>
            <pre className="whitespace-pre-wrap rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">{notes}</pre>
          </div>
        ) : null}
        <p className="text-xs text-slate-400">Просмотр записан в журнал событий. Окно закроется автоматически.</p>
      </div>
    </Modal>
  );
}

// --------------------------------------------------------------------------- //
// create / edit form                                                         //
// --------------------------------------------------------------------------- //
const EMPTY_FORM: CredentialInput = {
  title: "",
  category: "other",
  username: "",
  secret: "",
  host: "",
  location: "",
  url: "",
  notes: "",
  tags: "",
};

function CredentialFormModal({
  initial,
  onClose,
  onSaved,
}: {
  initial: Credential | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<CredentialInput>(() =>
    initial
      ? {
          title: initial.title,
          category: initial.category,
          username: initial.username ?? "",
          secret: "",
          host: initial.host ?? "",
          location: initial.location ?? "",
          url: initial.url ?? "",
          notes: initial.notes ?? "",
          tags: initial.tags ?? "",
        }
      : EMPTY_FORM,
  );
  const [showSecret, setShowSecret] = useState(!initial);
  const [showGen, setShowGen] = useState(false);

  const set = <K extends keyof CredentialInput>(key: K, value: CredentialInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const saveMut = useMutation({
    mutationFn: () => {
      if (initial) {
        const patch: Partial<CredentialInput> = { ...form };
        if (!patch.secret) delete patch.secret; // keep the stored secret
        return updateCredential(initial.id, patch);
      }
      return createCredential(form);
    },
    onSuccess: () => {
      showToast(initial ? "Запись обновлена" : "Запись добавлена", "success");
      onSaved();
    },
    onError: () => showToast("Не удалось сохранить запись", "error"),
  });

  const canSave = form.title.trim().length > 0 && (Boolean(initial) || (form.secret ?? "").length > 0);

  return (
    <Modal onClose={onClose} title={initial ? "Редактировать запись" : "Новая запись"} wide>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Название *" className="sm:col-span-2">
          <input className="app-input w-full py-2 px-3 text-sm" value={form.title} onChange={(e) => set("title", e.target.value)} />
        </Field>
        <Field label="Категория">
          <select
            className="app-input w-full py-2 px-3 text-sm"
            value={form.category}
            onChange={(e) => set("category", e.target.value as CredentialCategory)}
          >
            {CREDENTIAL_CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Магазин / площадка">
          <input className="app-input w-full py-2 px-3 text-sm" value={form.location ?? ""} onChange={(e) => set("location", e.target.value)} />
        </Field>
        <Field label="Логин">
          <input className="app-input w-full py-2 px-3 text-sm" value={form.username ?? ""} onChange={(e) => set("username", e.target.value)} />
        </Field>
        <Field label="Хост / IP">
          <input className="app-input w-full py-2 px-3 text-sm" value={form.host ?? ""} onChange={(e) => set("host", e.target.value)} />
        </Field>
        <Field label={initial ? "Новый пароль (пусто — не менять)" : "Пароль *"} className="sm:col-span-2">
          <div className="flex items-center gap-2">
            <input
              type={showSecret ? "text" : "password"}
              className="app-input w-full py-2 px-3 font-mono text-sm"
              value={form.secret ?? ""}
              onChange={(e) => set("secret", e.target.value)}
              autoComplete="new-password"
            />
            <button type="button" className="app-btn-secondary rounded-lg p-2" onClick={() => setShowSecret((s) => !s)}>
              {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
            <button type="button" className="app-btn-secondary rounded-lg p-2" title="Генератор" onClick={() => setShowGen((s) => !s)}>
              <Wand2 className="h-4 w-4" />
            </button>
          </div>
        </Field>
        {showGen ? (
          <div className="sm:col-span-2">
            <InlineGenerator onUse={(pw) => { set("secret", pw); setShowSecret(true); }} />
          </div>
        ) : null}
        <Field label="URL веб-панели" className="sm:col-span-2">
          <input className="app-input w-full py-2 px-3 text-sm" value={form.url ?? ""} onChange={(e) => set("url", e.target.value)} placeholder="https://" />
        </Field>
        <Field label="Теги (через запятую)" className="sm:col-span-2">
          <input className="app-input w-full py-2 px-3 text-sm" value={form.tags ?? ""} onChange={(e) => set("tags", e.target.value)} />
        </Field>
        <Field label="Заметки" className="sm:col-span-2">
          <textarea
            className="app-input w-full py-2 px-3 text-sm"
            rows={3}
            value={form.notes ?? ""}
            onChange={(e) => set("notes", e.target.value)}
          />
        </Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <button className="app-btn-secondary px-4 py-2 text-sm" onClick={onClose}>
          Отмена
        </button>
        <button
          className="app-btn-primary px-4 py-2 text-sm disabled:opacity-50"
          disabled={!canSave || saveMut.isPending}
          onClick={() => saveMut.mutate()}
        >
          {saveMut.isPending ? "Сохранение..." : "Сохранить"}
        </button>
      </div>
    </Modal>
  );
}

// --------------------------------------------------------------------------- //
// generator                                                                  //
// --------------------------------------------------------------------------- //
function GeneratorSection() {
  return (
    <SectionCard className="space-y-4">
      <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
        <Wand2 className="h-4 w-4" />
        <h2 className="text-base font-semibold">Генератор паролей</h2>
      </div>
      <InlineGenerator />
    </SectionCard>
  );
}

const MIN_LENGTH = 8;
const MAX_LENGTH = 128;

function InlineGenerator({ onUse }: { onUse?: (password: string) => void }) {
  const [params, setParams] = useState<PasswordGenParams>(DEFAULT_PARAMS);
  const [result, setResult] = useState<LocalPasswordResult>(() => generatePasswordLocal(DEFAULT_PARAMS));
  const [lengthText, setLengthText] = useState(String(DEFAULT_PARAMS.length));

  const regenerate = (p: PasswordGenParams) => setResult(generatePasswordLocal(p));

  const patch = (next: Partial<PasswordGenParams>) => {
    const merged = { ...params, ...next };
    setParams(merged);
    regenerate(merged);
  };

  const commitLength = (raw: string) => {
    const n = parseInt(raw, 10);
    const clamped = Number.isFinite(n) ? Math.min(MAX_LENGTH, Math.max(MIN_LENGTH, n)) : params.length;
    setLengthText(String(clamped));
    if (clamped !== params.length) patch({ length: clamped });
  };

  const classCount = ["uppercase", "lowercase", "digits", "symbols"].filter(
    (k) => params[k as keyof PasswordGenParams],
  ).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <code
          data-testid="generated-password"
          className="flex-1 min-w-[220px] break-all rounded-lg bg-slate-100 px-3 py-2.5 font-mono text-sm dark:bg-slate-800"
        >
          {result.error ? <span className="text-rose-500">{result.error}</span> : result.password}
        </code>
        <button className="app-btn-secondary inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm" onClick={() => regenerate(params)}>
          <RefreshCw className="h-4 w-4" />
          Обновить
        </button>
        <button
          className="app-btn-secondary inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm disabled:opacity-40"
          disabled={!!result.error}
          onClick={() => copyText(result.password, "Пароль")}
        >
          <Copy className="h-4 w-4" />
          Копировать
        </button>
        {onUse ? (
          <button
            className="app-btn-primary inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm disabled:opacity-40"
            disabled={!!result.error}
            onClick={() => onUse(result.password)}
          >
            Вставить
          </button>
        ) : null}
      </div>

      <div className="space-y-3">
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600 dark:text-slate-300">Длина ({MIN_LENGTH}–{MAX_LENGTH})</span>
          <input
            type="number"
            inputMode="numeric"
            min={MIN_LENGTH}
            max={MAX_LENGTH}
            className="app-input w-28 py-2 px-3 text-sm"
            value={lengthText}
            onChange={(e) => {
              setLengthText(e.target.value);
              const n = parseInt(e.target.value, 10);
              if (Number.isFinite(n) && n >= MIN_LENGTH && n <= MAX_LENGTH) patch({ length: n });
            }}
            onBlur={(e) => commitLength(e.target.value)}
          />
        </label>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Toggle label="A-Z" checked={params.uppercase} disabled={classCount === 1 && params.uppercase} onChange={(v) => patch({ uppercase: v })} />
          <Toggle label="a-z" checked={params.lowercase} disabled={classCount === 1 && params.lowercase} onChange={(v) => patch({ lowercase: v })} />
          <Toggle label="0-9" checked={params.digits} disabled={classCount === 1 && params.digits} onChange={(v) => patch({ digits: v })} />
          <Toggle label="!@#$" checked={params.symbols} disabled={classCount === 1 && params.symbols} onChange={(v) => patch({ symbols: v })} />
        </div>

        <div className="flex flex-wrap gap-4">
          <Toggle label="Без похожих (Il1O0…)" checked={params.exclude_ambiguous} onChange={(v) => patch({ exclude_ambiguous: v })} />
          <Toggle label="Минимум по одному из класса" checked={params.min_of_each} onChange={(v) => patch({ min_of_each: v })} />
        </div>

        <label className="block text-sm">
          <span className="mb-1 block text-slate-600 dark:text-slate-300">Исключить символы</span>
          <input
            className="app-input w-full py-2 px-3 font-mono text-sm"
            value={params.exclude_chars}
            maxLength={64}
            onChange={(e) => patch({ exclude_chars: e.target.value })}
            placeholder="например: {}[]/"
          />
        </label>
      </div>
    </div>
  );
}

function Toggle({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className={`inline-flex items-center gap-2 text-sm ${disabled ? "opacity-50" : "cursor-pointer"}`}>
      <input
        type="checkbox"
        className="h-4 w-4 accent-[var(--brand)]"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="text-slate-600 dark:text-slate-300">{label}</span>
    </label>
  );
}

// --------------------------------------------------------------------------- //
// shared bits                                                                //
// --------------------------------------------------------------------------- //
function Field({ label, className = "", children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={`block text-sm ${className}`}>
      <span className="mb-1 block text-slate-600 dark:text-slate-300">{label}</span>
      {children}
    </label>
  );
}

function Modal({
  title,
  onClose,
  wide,
  children,
}: {
  title: string;
  onClose: () => void;
  wide?: boolean;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-label={title}
        className={`app-panel w-full ${wide ? "max-w-2xl" : "max-w-md"} max-h-[90vh] overflow-y-auto p-5`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
          <button className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
