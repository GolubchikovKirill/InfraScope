/** Human-readable text for a device's `reachability_reason`.
 *
 * The backend speaks three dialects here, because the three probes grew
 * separately: SSH (switches) says `dns_failure`/`connection_refused`, the TCP
 * probe (printers, computers, cash registers) says
 * `dns_unresolved`/`port_closed`, and SNMP says `no_response`/`poll_error`.
 * Several pairs are the same fact under different names - they are mapped to
 * the same text below and marked as aliases, so that when the backend
 * vocabulary is unified the duplicates here can simply be deleted.
 */
const REASON_TEXT: Record<string, string> = {
  // --- naming ---
  dns_unresolved: "Имя хоста не резолвится",
  dns_failure: "Имя хоста не резолвится", // alias of dns_unresolved (SSH)

  // --- routing ---
  no_route: "Нет маршрута до устройства",
  network_unreachable: "Нет маршрута до устройства", // alias of no_route (SSH)
  host_unreachable: "Нет маршрута до устройства", // alias of no_route (legacy rows)

  // --- host up, service not answering ---
  port_closed: "Порт закрыт",
  connection_refused: "Порт закрыт", // alias of port_closed (SSH)

  // --- no answer at all ---
  no_response: "Нет ответа",
  timeout: "Нет ответа (таймаут)",

  // --- the probe itself, not a verdict about the device ---
  poll_error: "Ошибка при опросе",
  probe_error: "Сбой самой проверки",
  protocol_error: "Ошибка протокола SSH",
  auth_rejected: "Неверные учётные данные",
  target_invalid: "Некорректный адрес устройства",
};

/** Every `reachability_reason` the backend currently emits, across all three
 *  probe dialects. Kept open-ended: unknown values render as "неизвестная
 *  причина" rather than breaking the build when the backend adds one. */
export type ReachabilityReason = keyof typeof REASON_TEXT | (string & {});

export function describeOfflineReason(reason: string | null | undefined): string {
  if (!reason) return "Причина неизвестна";
  return REASON_TEXT[reason] ?? "Неизвестная причина";
}
