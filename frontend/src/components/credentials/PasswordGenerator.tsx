// Local password generator: the standalone section and the inline one the form embeds.
import { useState } from "react";
import { Copy, RefreshCw, Wand2 } from "lucide-react";
import { SectionCard } from "../../components/ui/AsyncState";
import { DEFAULT_PARAMS, generatePasswordLocal, type LocalPasswordResult } from "../../lib/passwordGen";
import type { PasswordGenParams } from "../../api/credentials";
import { copyText, Toggle } from "./shared";

export function GeneratorSection() {
  return (
    <SectionCard className="space-y-4">
      <div className="flex items-center gap-2 text-slate-900">
        <Wand2 className="h-4 w-4" />
        <h2 className="text-base font-semibold">Генератор паролей</h2>
      </div>
      <InlineGenerator />
    </SectionCard>
  );
}

const MIN_LENGTH = 6;
const MAX_LENGTH = 128;

export function InlineGenerator({ onUse }: { onUse?: (password: string) => void }) {
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
          className="flex-1 min-w-[220px] break-all rounded-lg bg-slate-100 px-3 py-2.5 font-mono text-sm"
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
          <span className="mb-1 block text-slate-600">Длина ({MIN_LENGTH}–{MAX_LENGTH})</span>
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
          <span className="mb-1 block text-slate-600">Исключить символы</span>
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
