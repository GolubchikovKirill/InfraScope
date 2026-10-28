// Create / edit a vault entry.
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Eye, EyeOff, Wand2 } from "lucide-react";
import {
  CREDENTIAL_CATEGORIES,
  createCredential,
  updateCredential,
  type Credential,
  type CredentialCategory,
  type CredentialInput,
} from "../../client";
import { showToast } from "../../lib/toastBus";
import { Field, Modal } from "./shared";
import { InlineGenerator } from "./PasswordGenerator";

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

export function CredentialFormModal({
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
