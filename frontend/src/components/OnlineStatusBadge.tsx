export default function OnlineStatusBadge({ isOnline }: { isOnline: boolean | null }) {
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
