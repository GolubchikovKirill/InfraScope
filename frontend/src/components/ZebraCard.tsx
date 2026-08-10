import { RefreshCw, Pencil, Trash2, Tag, ExternalLink, Usb } from "lucide-react";
import type { Printer } from "../client";
import OnlineStatusBadge from "./OnlineStatusBadge";

interface Props {
  printer: Printer;
  onPoll: (id: string) => void;
  onEdit: (printer: Printer) => void;
  onDelete: (id: string) => void;
  isPolling: boolean;
  isSuperuser: boolean;
}

function statusBadge(printer: Printer) {
  if (printer.connection_type === "usb") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-violet-600">
        <Usb className="h-3 w-3" />
        USB
      </span>
    );
  }
  return <OnlineStatusBadge isOnline={printer.is_online} />;
}

export default function ZebraCard({ printer, onPoll, onEdit, onDelete, isPolling, isSuperuser }: Props) {
  const isUsb = printer.connection_type === "usb";

  const polledAt = printer.last_polled_at
    ? new Date(printer.last_polled_at).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })
    : null;

  return (
    <div className="app-panel app-card rounded-xl border shadow-sm hover:shadow-md transition flex flex-col">
      <div className="p-5 flex flex-col gap-3">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="app-entity-icon">
              {isUsb ? <Usb className="h-5 w-5" /> : <Tag className="h-5 w-5" />}
            </div>
            <div className="min-w-0">
              <div className="app-card-title truncate">{printer.model}</div>
              <div className="app-card-meta app-mono">{printer.store_name}</div>
            </div>
          </div>
          {statusBadge(printer)}
        </div>

        {/* IP or Host PC */}
        {isUsb ? (
          printer.host_pc && (
            <div className="text-xs text-gray-400">
              <span className="text-gray-500">Hostname / ПК:</span> {printer.host_pc}
            </div>
          )
        ) : (
          <div className="space-y-1">
            <div className="text-xs text-gray-400 font-mono">{printer.ip_address}</div>
            {printer.host_pc && (
              <div className="text-xs text-gray-500">
                <span className="text-gray-400">Hostname:</span> {printer.host_pc}
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-2 border-t border-gray-100">
          <span className="text-[11px] text-gray-400">
            {isUsb
              ? "Подключение: USB"
              : polledAt ? `Проверено: ${polledAt}` : "Ещё не проверялся"
            }
          </span>
          <div className="flex items-center gap-1">
            {!isUsb && (
              <>
                <button
                  onClick={() => onPoll(printer.id)}
                  disabled={isPolling}
                  className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-blue-600 transition disabled:opacity-40"
                  title="Проверить"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${isPolling ? "animate-spin" : ""}`} />
                </button>
                {printer.ip_address && (
                  <a
                    href={`http://${printer.ip_address}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-blue-600 transition"
                    title="Веб-панель"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                )}
              </>
            )}
            {isSuperuser && (
              <>
                <button
                  onClick={() => onEdit(printer)}
                  className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-amber-600 transition"
                  title="Редактировать"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={() => onDelete(printer.id)}
                  className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-red-600 transition"
                  title="Удалить"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </div>
        </div>
      </div>

    </div>
  );
}
