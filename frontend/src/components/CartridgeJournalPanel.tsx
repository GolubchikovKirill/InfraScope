import type { CartridgeLifeStats, CartridgeReplacement } from "../client";

const COLOR_LABEL: Record<string, string> = { black: "K", cyan: "C", magenta: "M", yellow: "Y" };

function formatDate(value: string): string {
  return new Date(value).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function formatDays(days: number | null): string {
  return days == null ? "—" : `${Math.round(days)} дн.`;
}

function formatPages(pages: number | null): string {
  return pages == null ? "—" : pages.toLocaleString("ru-RU");
}

interface Props {
  rows: CartridgeReplacement[];
  stats: CartridgeLifeStats[];
  loading: boolean;
}

/**
 * Cartridge swaps detected by polling, and how long each cartridge model
 * actually lasts. Nobody fills this in - a level jumping up by a refill's worth
 * between two polls is the record. Lifetime and pages need a previous swap on
 * the same printer and colour, so the first swap seen for a printer has none.
 */
export default function CartridgeJournalPanel({ rows, stats, loading }: Props) {
  const measured = stats.filter((s) => s.median_lifetime_days != null || s.median_pages != null);

  return (
    <section className="space-y-3" aria-label="Журнал замен картриджей">
      <div className="app-panel p-3">
        <div className="text-sm font-semibold text-[var(--text-strong)]">Журнал замен</div>
        <div className="text-xs text-[var(--text-faint)]">
          Замены фиксируются автоматически: уровень тонера вырос на 15 пунктов и больше между опросами
        </div>
      </div>

      {measured.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {measured.map((s) => (
            <div key={`${s.cartridge_name}:${s.toner_color}`} className="app-stat px-3 py-2 text-xs">
              <div className="font-semibold text-[var(--text-strong)]">
                {s.cartridge_name} <span className="text-[var(--text-faint)]">{COLOR_LABEL[s.toner_color] ?? ""}</span>
              </div>
              <div className="text-[var(--text-muted)]">
                служит {formatDays(s.median_lifetime_days)}
                {s.median_pages != null && <> · {formatPages(s.median_pages)} стр.</>}
                <span className="text-[var(--text-faint)]"> · замен: {s.replacements}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {loading ? (
        <div className="app-panel p-6 text-center text-sm text-[var(--text-faint)]">Загрузка...</div>
      ) : rows.length === 0 ? (
        <div className="app-empty p-6 text-center text-sm text-[var(--text-faint)]">
          Замен пока не было - журнал начнёт заполняться со следующей замены картриджа
        </div>
      ) : (
        <div className="app-table-wrap">
          <table className="app-table min-w-full">
            <thead>
              <tr>
                <th>Когда</th>
                <th>Магазин</th>
                <th>Цвет</th>
                <th>Картридж</th>
                <th className="num">Уровень</th>
                <th className="num">Прослужил</th>
                <th className="num">Страниц</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="app-mono whitespace-nowrap">{formatDate(row.replaced_at)}</td>
                  <td>
                    <div className="font-medium text-[var(--text-strong)]">{row.store_name}</div>
                    {row.printer_model && <div className="app-card-meta">{row.printer_model}</div>}
                  </td>
                  <td>{COLOR_LABEL[row.toner_color] ?? row.toner_color}</td>
                  <td>{row.cartridge_name ?? "—"}</td>
                  <td className="num app-mono">
                    {row.level_before}% → {row.level_after}%
                  </td>
                  <td className="num">{formatDays(row.lifetime_days)}</td>
                  <td className="num">{formatPages(row.pages_printed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
