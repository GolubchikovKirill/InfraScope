import { useObservationTime } from "../hooks/useObservationTime";

export default function OnlineStatusBadge({ isOnline, lastPolledAt }: { isOnline: boolean | null; lastPolledAt?: string | null }) {
  const now = useObservationTime();
  const measuredAt = Date.parse(lastPolledAt ?? "");
  if (lastPolledAt !== undefined && isOnline !== null && (!Number.isFinite(measuredAt) || now - measuredAt > 30 * 60_000)) {
    return <span className="app-status app-status-unknown" title={lastPolledAt ?? "Время проверки неизвестно"}><span className="mark" />Данные устарели</span>;
  }
  if (isOnline === null) {
    return (
      <span className="app-status app-status-unknown">
        <span className="mark" />
        Не проверен
      </span>
    );
  }
  if (isOnline) {
    return (
      <span className="app-status app-status-ok">
        <span className="mark" />
        Онлайн
      </span>
    );
  }
  return (
    <span className="app-status app-status-off">
      <span className="mark" />
      Оффлайн
    </span>
  );
}
