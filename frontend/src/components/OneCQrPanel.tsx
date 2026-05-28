import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Download, QrCode, Server } from "lucide-react";
import { exportQrGenerator } from "../client";
import { ErrorState, FormActions } from "./ui/AsyncState";

type DatabaseMode = "duty_free" | "duty_paid" | "both";

type FormState = {
  db_mode: DatabaseMode;
  airport_code: string;
  surnames: string;
  add_login: boolean;
};

const initialState: FormState = {
  db_mode: "duty_free",
  airport_code: "4007",
  surnames: "",
  add_login: false,
};

export default function OneCQrPanel() {
  const [form, setForm] = useState<FormState>(initialState);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const exportMut = useMutation({
    mutationFn: exportQrGenerator,
    onSuccess: (blob) => {
      const date = new Date().toISOString().slice(0, 10);
      const link = document.createElement("a");
      const url = URL.createObjectURL(blob);
      link.href = url;
      link.download = `qr_export_${date}.zip`;
      link.click();
      URL.revokeObjectURL(url);
      setError(null);
      setMessage("Архив сформирован и скачан.");
    },
    onError: (e: unknown) => {
      setMessage(null);
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "Не удалось сформировать выгрузку.");
    },
  });

  const runExport = () => {
    setError(null);
    setMessage(null);
    exportMut.mutate({
      db_mode: form.db_mode,
      airport_code: form.airport_code.trim(),
      surnames: form.surnames.trim() || undefined,
      add_login: form.add_login,
    });
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">База для выгрузки</span>
          <select
            className="app-input w-full py-2 px-3 text-sm"
            value={form.db_mode}
            onChange={(e) => setForm((s) => ({ ...s, db_mode: e.target.value as DatabaseMode }))}
          >
            <option value="duty_free">Duty Free (DC1-SRV-KC01.regstaer.local)</option>
            <option value="duty_paid">Duty Paid (DC1-SRV-KC02.regstaer.local)</option>
            <option value="both">Обе базы (Duty Free + Duty Paid)</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">Источник данных</span>
          <div className="app-input w-full py-2 px-3 text-sm text-slate-600">
            SQL credentials берутся автоматически из backend (.env)
          </div>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">Код аэропорта (LOGIN prefix)</span>
          <input
            className="app-input w-full py-2 px-3 text-sm"
            value={form.airport_code}
            onChange={(e) => setForm((s) => ({ ...s, airport_code: e.target.value }))}
            placeholder="4007"
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">Фамилии (через запятую, опционально)</span>
          <input
            className="app-input w-full py-2 px-3 text-sm"
            value={form.surnames}
            onChange={(e) => setForm((s) => ({ ...s, surnames: e.target.value }))}
            placeholder="Иванов, Петров"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <label className="inline-flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={form.add_login}
            onChange={(e) => setForm((s) => ({ ...s, add_login: e.target.checked }))}
          />
          Добавлять логин/ID мелким текстом
        </label>
      </div>

      <FormActions>
        <button
          onClick={runExport}
          disabled={exportMut.isPending}
          className="app-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm"
        >
          {exportMut.isPending ? <Server className="h-4 w-4 animate-spin" /> : <QrCode className="h-4 w-4" />}
          {exportMut.isPending ? "Формирование..." : "Сформировать и скачать ZIP"}
        </button>
        <button
          onClick={() => {
            setForm(initialState);
            setMessage(null);
            setError(null);
          }}
          className="app-btn-secondary inline-flex items-center gap-2 px-4 py-2 text-sm"
        >
          <Download className="h-4 w-4" />
          Сбросить
        </button>
      </FormActions>

      {message && <div className="text-sm text-emerald-700">{message}</div>}
      {error && <ErrorState text={error} />}
    </div>
  );
}
