export default function OnlineStatusBadge({ isOnline }: { isOnline: boolean | null }) {
  if (isOnline === null) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-gray-400">
        <span className="h-2 w-2 rounded-full bg-gray-300" />
        Не проверен
      </span>
    );
  }
  if (isOnline) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-emerald-600">
        <span className="h-2 w-2 rounded-full bg-emerald-500" />
        Онлайн
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-red-500">
      <span className="h-2 w-2 rounded-full bg-red-500" />
      Оффлайн
    </span>
  );
}
