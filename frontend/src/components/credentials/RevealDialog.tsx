// Shows a revealed secret once, with copy, and forgets it on close.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Copy,
  ExternalLink,
  Eye,
  EyeOff,
  MonitorSmartphone,
} from "lucide-react";
import { copyText, Modal } from "./shared";

export function RevealDialog({
  title,
  secret,
  notes,
  deviceHref,
  connectHref,
  onClose,
}: {
  title: string;
  secret: string;
  notes: string | null;
  deviceHref: string | null;
  connectHref: string | null;
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
            <code className="flex-1 break-all rounded-lg bg-slate-100 px-3 py-2 font-mono text-sm">
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
            <pre className="whitespace-pre-wrap rounded-lg bg-slate-100 px-3 py-2 text-sm">{notes}</pre>
          </div>
        ) : null}
        {(connectHref || deviceHref) && (
          <div className="flex flex-wrap gap-2 border-t border-[var(--app-panel-border)] pt-3">
            {connectHref && (
              <a href={connectHref} className="app-btn-primary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs">
                <MonitorSmartphone className="h-3.5 w-3.5" />
                Подключиться
              </a>
            )}
            {deviceHref && (
              <Link to={deviceHref} onClick={onClose} className="app-btn-secondary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs">
                <ExternalLink className="h-3.5 w-3.5" />
                Открыть устройство
              </Link>
            )}
          </div>
        )}
        <p className="text-xs text-slate-400">Просмотр записан в журнал событий. Окно закроется автоматически.</p>
      </div>
    </Modal>
  );
}
