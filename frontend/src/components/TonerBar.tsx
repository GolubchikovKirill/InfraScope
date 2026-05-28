import { Check, Copy } from "lucide-react";

interface TonerBarProps {
  label: string;
  level: number | null;
  color: string;
  bgColor: string;
  tonerName?: string | null;
  isCopied?: boolean;
  onCopy?: () => void;
}

export default function TonerBar({ label, level, color, bgColor, tonerName, isCopied = false, onCopy }: TonerBarProps) {
  const isNeverPolled = level === null;
  const isSomeRemaining = level === -3;
  const isUnknown = level === -2;
  const isSpecial = isNeverPolled || isSomeRemaining || isUnknown;
  const pct = isSpecial ? 0 : level;
  const canCopy = Boolean(tonerName && onCopy);
  const title = canCopy
    ? `Скопировать ${tonerName}`
    : isSomeRemaining
      ? "Есть тонер, точный уровень неизвестен"
      : isUnknown
        ? "Нет данных (неориг. чип)"
        : undefined;

  return (
    <button
      type="button"
      onClick={canCopy ? onCopy : undefined}
      disabled={!canCopy}
      className="group flex w-full items-center gap-2 rounded-md text-xs outline-none transition enabled:cursor-copy enabled:px-1 enabled:py-0.5 enabled:hover:bg-slate-50 enabled:focus-visible:ring-2 enabled:focus-visible:ring-blue-500 disabled:cursor-default"
      title={title}
    >
      <span className="w-7 text-gray-500 font-medium shrink-0">{label}</span>
      <div className={`flex-1 h-3 rounded-full ${bgColor} overflow-hidden`}>
        {!isSpecial && (
          <div
            className={`h-full rounded-full transition-all duration-500 ${color}`}
            style={{ width: `${pct}%` }}
          />
        )}
        {isSomeRemaining && (
          <div className={`h-full w-[15%] rounded-full ${color} opacity-50`} />
        )}
        {(isUnknown || isNeverPolled) && (
          <div className="h-full w-full bg-gray-200 flex items-center justify-center">
            <span className="text-[9px] text-gray-400">?</span>
          </div>
        )}
      </div>
      <span className="w-14 text-right text-gray-500 shrink-0 truncate">
        {isNeverPolled ? "—" : isSomeRemaining ? "Есть" : isUnknown ? "Нет данных" : `${pct}%`}
      </span>
      {canCopy && (
        <span className="flex w-4 shrink-0 justify-end">
          {isCopied ? (
            <Check className="h-3.5 w-3.5 text-emerald-600" />
          ) : (
            <Copy className="h-3.5 w-3.5 text-gray-400 opacity-0 transition group-hover:opacity-100 group-focus-visible:opacity-100" />
          )}
        </span>
      )}
    </button>
  );
}
