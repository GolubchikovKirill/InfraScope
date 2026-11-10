/** PostgreSQL timestamps without an offset in the API represent UTC. */
export function parseApiTimestamp(value: string | null | undefined): number {
  if (!value) return Number.NaN;
  const timestamp = value.trim().replace(" ", "T");
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp);
  return Date.parse(hasOffset ? timestamp : `${timestamp}Z`);
}
