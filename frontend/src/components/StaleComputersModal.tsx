import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, X } from "lucide-react";
import { deleteComputer, getStaleComputers, type StaleComputer } from "../client";
import { useConfirm } from "./ConfirmDialog";
import { useEscapeKey } from "../hooks/useEscapeKey";
import { relTime } from "../lib/relTime";
import { showToast } from "../lib/toastBus";

/** Leftovers of the AD import: computers the RustDesk console has never seen and that do
 *  not answer a ping. Nothing is removed until a person ticks rows and confirms; laptops
 *  start unticked because a laptop off the office network looks exactly the same. */
export default function StaleComputersModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const pressedOnBackdrop = useRef(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  useEscapeKey(true, onClose);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["computers", "stale"],
    queryFn: getStaleComputers,
    retry: false,
    refetchOnWindowFocus: false,
  });

  // preselect everything except laptops, once, when the list first arrives
  useEffect(() => {
    if (data) setPicked(new Set(data.data.filter((c) => !c.laptop_like).map((c) => c.id)));
  }, [data]);

  const removeMut = useMutation({
    mutationFn: async (rows: StaleComputer[]) => {
      const failed: string[] = [];
      let removed = 0;
      for (const row of rows) {
        try {
          await deleteComputer(row.id);
          removed += 1;
        } catch {
          failed.push(row.hostname);
        }
      }
      return { removed, failed };
    },
    onSuccess: ({ removed, failed }) => {
      if (removed) showToast(`Удалено компьютеров: ${removed}`, "success");
      if (failed.length) showToast(`Не удалось удалить: ${failed.join(", ")}`, "error");
      qc.invalidateQueries({ queryKey: ["computers"] });
      qc.invalidateQueries({ queryKey: ["remote-devices"] });
    },
  });

  const rows = data?.data ?? [];
  const selected = rows.filter((row) => picked.has(row.id));
  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const submit = async () => {
    const withRemote = selected.filter((row) => row.in_remote_access).length;
    const ok = await confirm(
      `Удалить компьютеров: ${selected.length}? Записи уйдут из списка компьютеров${withRemote ? `, ${withRemote} из них также из удалённого доступа` : ""}. ` +
        "Сами машины никак не затрагиваются. Вернуть можно только заведя заново.",
      { danger: true, confirmText: "Удалить" },
    );
    if (ok) removeMut.mutate(selected);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onMouseDown={(e) => {
        pressedOnBackdrop.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && pressedOnBackdrop.current) onClose();
        pressedOnBackdrop.current = false;
      }}
    >
      <div role="dialog" aria-label="Неактуальные компьютеры" className="app-panel flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden">
        <header className="flex items-start justify-between gap-3 border-b border-[var(--app-panel-border)] px-5 py-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Неактуальные компьютеры</h3>
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
              Их нет в консоли RustDesk и они не отвечают на пинг, скорее всего это остатки импорта из AD.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Закрыть" className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800">
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
          {isLoading ? (
            <p className="py-8 text-center text-sm text-slate-500">Сверяю с консолью…</p>
          ) : isError ? (
            <p className="py-8 text-center text-sm text-slate-600 dark:text-slate-300">Не удалось получить список. Попробуйте позже.</p>
          ) : !data?.console_reachable ? (
            <p className="py-8 text-center text-sm text-slate-600 dark:text-slate-300">
              Консоль RustDesk сейчас недоступна, поэтому судить о неактуальности нельзя. Ничего не показываю, чтобы не предложить удалить живые машины.
            </p>
          ) : rows.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-600 dark:text-slate-300">Неактуальных компьютеров нет: все есть в консоли или отвечают.</p>
          ) : (
            <>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="text-slate-600 dark:text-slate-300">Отмечено {selected.length} из {rows.length}</span>
                <span className="flex gap-3">
                  <button type="button" className="text-[var(--brand)] hover:underline" onClick={() => setPicked(new Set(rows.filter((r) => !r.laptop_like).map((r) => r.id)))}>
                    Все, кроме ноутбуков
                  </button>
                  <button type="button" className="text-[var(--brand)] hover:underline" onClick={() => setPicked(new Set())}>
                    Снять всё
                  </button>
                </span>
              </div>
              <ul className="divide-y divide-[var(--app-panel-border)]">
                {rows.map((row) => (
                  <li key={row.id}>
                    <label className="flex cursor-pointer items-start gap-3 py-2.5">
                      <input type="checkbox" className="mt-1" checked={picked.has(row.id)} onChange={() => toggle(row.id)} aria-label={`Удалить ${row.hostname}`} />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-sm font-medium text-slate-900 dark:text-slate-100">{row.hostname}</span>
                          {row.laptop_like && (
                            <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300" title="Ноутбук может быть просто вне сети офиса">
                              ноутбук
                            </span>
                          )}
                          {row.in_remote_access && <span className="rounded-full border border-slate-300 bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300">в удалённом доступе</span>}
                        </span>
                        <span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">
                          {[row.location && `магазин ${row.location}`, row.last_polled_at ? `опрос ${relTime(row.last_polled_at)}` : "не опрашивался", row.comment].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-[var(--app-panel-border)] px-5 py-3">
          <button type="button" onClick={onClose} className="app-btn-secondary px-4 py-2 text-sm">Закрыть</button>
          <button
            type="button"
            onClick={submit}
            disabled={selected.length === 0 || removeMut.isPending}
            className="app-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" />
            {removeMut.isPending ? "Удаляю…" : `Удалить выбранные (${selected.length})`}
          </button>
        </footer>
      </div>
    </div>
  );
}
