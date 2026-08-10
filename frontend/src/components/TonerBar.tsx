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
  const valueText = isNeverPolled ? "—" : isSomeRemaining ? "Есть" : isUnknown ? "Нет данных" : `${pct}%`;
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
      className="app-toner-row group w-full text-left outline-none transition enabled:cursor-copy enabled:hover:bg-[var(--surface-2)] disabled:cursor-default"
      title={title}
      // Stated outright rather than left to the browser to stitch together from
      // the label and value fragments, which produced "K12%" with no separator.
      aria-label={`${label} ${valueText}${tonerName ? `, ${tonerName}` : ""}`}
    >
      <span className="app-toner-label">{label}</span>
      <span className={`app-toner-track ${isSpecial ? bgColor : ""}`}>
        {!isSpecial && <span className={`app-toner-fill ${color}`} style={{ width: `${pct}%` }} />}
        {isSomeRemaining && <span className={`app-toner-fill w-[15%] opacity-50 ${color}`} />}
        {(isUnknown || isNeverPolled) && (
          <span className="flex h-full w-full items-center justify-center bg-[var(--surface-3)] text-[9px] text-[var(--text-faint)]">
            ?
          </span>
        )}
      </span>
      <span className="app-toner-value truncate">{valueText}</span>
      <span className="flex justify-end">
        {canCopy &&
          (isCopied ? (
            <Check className="h-3.5 w-3.5 text-[var(--ok-fg)]" />
          ) : (
            <Copy className="h-3.5 w-3.5 text-[var(--text-faint)] opacity-0 transition group-hover:opacity-100 group-focus-visible:opacity-100" />
          ))}
      </span>
    </button>
  );
}
