import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Plane, RotateCcw } from "lucide-react";
import { exportBoardingPass } from "../client";
import { ErrorState, FormActions } from "./ui/AsyncState";

type BarcodeFormat = "aztec" | "pdf417";

type FormState = {
  format: BarcodeFormat;
  from_code: string;
  to_code: string;
  raw_data: string;
};

const DEFAULT_BOARDING_TEMPLATE = {
  first_name: "JOHN",
  last_name: "DOE",
  booking_ref: "XYZ123",
  flight_operator: "BA",
  flight_number: "1234",
  travel_class: "Y",
  seat: "35A",
  boarding_index: "0001",
} as const;

function getTodayDefaults() {
  const today = new Date();
  const yearStart = new Date(today.getFullYear(), 0, 0);
  const dayInYear = String(
    Math.floor((today.getTime() - yearStart.getTime()) / 86_400_000),
  ).padStart(3, "0");

  return {
    flight_date: today.toISOString().slice(0, 10),
    day_in_year: dayInYear,
  };
}

function createInitialState(): FormState {
  return {
    format: "aztec",
    from_code: "SVO",
    to_code: "LED",
    raw_data: "",
  };
}

function normalizeAirportCode(value: string) {
  return value.replace(/[^a-zA-Z]/g, "").slice(0, 3).toUpperCase();
}

function buildPresetPayload(form: FormState) {
  const { flight_date, day_in_year } = getTodayDefaults();
  return {
    format: form.format,
    first_name: DEFAULT_BOARDING_TEMPLATE.first_name,
    last_name: DEFAULT_BOARDING_TEMPLATE.last_name,
    booking_ref: DEFAULT_BOARDING_TEMPLATE.booking_ref,
    from_code: form.from_code,
    to_code: form.to_code,
    flight_operator: DEFAULT_BOARDING_TEMPLATE.flight_operator,
    flight_number: DEFAULT_BOARDING_TEMPLATE.flight_number,
    flight_date,
    day_in_year,
    travel_class: DEFAULT_BOARDING_TEMPLATE.travel_class,
    seat: DEFAULT_BOARDING_TEMPLATE.seat,
    boarding_index: DEFAULT_BOARDING_TEMPLATE.boarding_index,
  };
}

export default function BoardingPassPanel() {
  const [form, setForm] = useState<FormState>(() => createInitialState());
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const exportMut = useMutation({
    mutationFn: exportBoardingPass,
    onSuccess: (blob) => {
      const date = new Date().toISOString().slice(0, 10);
      const link = document.createElement("a");
      const url = URL.createObjectURL(blob);
      link.href = url;
      link.download = `boarding_pass_${form.format}_${date}.png`;
      link.click();
      URL.revokeObjectURL(url);
      setError(null);
      setMessage("Файл boarding pass сформирован и скачан.");
    },
    onError: (e: unknown) => {
      setMessage(null);
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "Не удалось сформировать boarding pass.");
    },
  });

  const setField = <K extends keyof FormState>(field: K, value: FormState[K]) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  const canSubmit = Boolean(form.raw_data.trim() || (form.from_code.length === 3 && form.to_code.length === 3));

  const runExport = () => {
    setMessage(null);
    setError(null);
    exportMut.mutate(
      form.raw_data.trim()
        ? {
            format: form.format,
            raw_data: form.raw_data.trim(),
          }
        : buildPresetPayload(form),
    );
  };

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-[var(--app-panel-border)] bg-white/60 p-4 shadow-sm dark:bg-slate-900/30">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Простой режим генерации
            </div>
            <div className="text-xs text-slate-500">
              Заполните только маршрут. Остальные данные подставятся автоматически.
            </div>
          </div>
          <label className="text-sm min-w-40">
            <span className="mb-1 block text-slate-600">Симвология</span>
            <select
              className="app-input w-full py-2 px-3 text-sm"
              value={form.format}
              onChange={(e) => setField("format", e.target.value as BarcodeFormat)}
            >
              <option value="aztec">Aztec</option>
              <option value="pdf417">PDF417</option>
            </select>
          </label>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-sm">
            <span className="mb-1 block text-slate-600">Откуда</span>
            <input
              className="app-input w-full py-3 px-3 text-base font-medium tracking-[0.2em] uppercase"
              value={form.from_code}
              onChange={(e) => setField("from_code", normalizeAirportCode(e.target.value))}
              placeholder="SVO"
              maxLength={3}
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-slate-600">Куда</span>
            <input
              className="app-input w-full py-3 px-3 text-base font-medium tracking-[0.2em] uppercase"
              value={form.to_code}
              onChange={(e) => setField("to_code", normalizeAirportCode(e.target.value))}
              placeholder="LED"
              maxLength={3}
            />
          </label>
        </div>

        <div className="mt-4 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
          Шаблон по умолчанию: John Doe, BA1234, место 35A, сегодняшняя дата.
        </div>
      </div>

      <details className="rounded-xl border border-[var(--app-panel-border)] px-4 py-3">
        <summary className="cursor-pointer select-none text-sm font-medium text-slate-700 dark:text-slate-200">
          Расширенный режим
        </summary>
        <div className="mt-3">
          <label className="text-sm block">
            <span className="mb-1 block text-slate-600">Raw payload</span>
            <textarea
              className="app-input w-full py-2 px-3 text-sm min-h-24"
              value={form.raw_data}
              onChange={(e) => setField("raw_data", e.target.value)}
              placeholder="M1DOE/JOHN XYZ123 SVOLEDBA1234..."
            />
          </label>
          <div className="mt-2 text-xs text-slate-500">
            Если заполнить `raw payload`, backend использует его напрямую вместо автосборки.
          </div>
        </div>
      </details>

      <FormActions>
        <button
          type="button"
          onClick={runExport}
          disabled={exportMut.isPending || !canSubmit}
          className="app-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-60"
        >
          <Plane className="h-4 w-4" />
          {exportMut.isPending ? "Формирование..." : "Сформировать PNG"}
        </button>
        <button
          type="button"
          onClick={() => {
            setForm(createInitialState());
            setMessage(null);
            setError(null);
          }}
          className="app-btn-secondary inline-flex items-center gap-2 px-4 py-2 text-sm"
        >
          <RotateCcw className="h-4 w-4" />
          Сбросить
        </button>
        <div className="text-xs text-slate-500">
          Для автогенерации достаточно заполнить только `Откуда` и `Куда`.
        </div>
      </FormActions>

      {message && <div className="text-sm text-emerald-700">{message}</div>}
      {error && <ErrorState text={error} />}
    </div>
  );
}
