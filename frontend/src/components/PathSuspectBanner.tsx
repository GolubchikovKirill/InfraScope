import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { getEventLogs, type EventDeviceKind } from "../client";

// Poll cadence for every device kind is 15 minutes (see app/worker/celery_app.py).
// A poll_path_suspect event older than about one cycle-and-a-bit is stale -
// the next cycle already ran and either confirmed the path is back or
// raised a fresh event, so there is no reason to keep showing this one.
const RECENT_WINDOW_MS = 20 * 60_000;

function parseServerDate(value: string): Date {
  const hasTz = /(?:Z|[+\-]\d{2}:\d{2})$/.test(value);
  return new Date(hasTz ? value : `${value}Z`);
}

/**
 * Warns that a whole subnet's worth of devices stopped answering in one poll
 * cycle - see app.domains.inventory.{printer,switch}_polling._subnets_with_total_failure.
 * That heuristic deliberately leaves affected devices' online/offline state
 * untouched rather than guessing, so without this banner the only visible
 * trace is a warning buried in the event log: every device just looks like
 * it stopped updating, with no indication why. This is the exact blind spot
 * that took 3 days to diagnose during the Aug 10 network outage.
 */
export default function PathSuspectBanner({ deviceKind }: { deviceKind: EventDeviceKind }) {
  const { data } = useQuery({
    queryKey: ["path-suspect-events", deviceKind],
    queryFn: () => getEventLogs({ device_kind: deviceKind ?? undefined, q: "poll_path_suspect", limit: 5 }),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const recent = (data?.data ?? []).filter(
    (event) => Date.now() - parseServerDate(event.created_at).getTime() <= RECENT_WINDOW_MS
  );
  if (recent.length === 0) return null;

  const subnets = [...new Set(recent.map((e) => e.device_name).filter(Boolean))];
  const latest = recent[0];

  return (
    <div
      className="flex items-start gap-2 rounded-lg bg-[var(--warn-bg)] border border-[var(--warn-border)] px-3 py-2 text-sm text-[var(--warn-fg)]"
      title={latest.message}
    >
      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
      <span>
        Обрыв пути до подсети{subnets.length > 1 ? "ей" : ""} {subnets.join(", ")}: часть устройств не опрошена в
        последнем цикле, их статус может быть неактуален. Восстановится автоматически, когда путь вернётся.
      </span>
    </div>
  );
}
