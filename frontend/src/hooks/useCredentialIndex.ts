import { useQuery } from "@tanstack/react-query";
import { getCredentials } from "../client";
import { useAuth } from "../auth";
import { normalizeHostKey } from "../lib/deviceLinks";

/** One cached fetch of the whole vault, bucketed by normalized host, so any
 *  device row can show "Пароли (N)" -> /credentials?q=<host> without its own
 *  request. /credentials is superuser-only, so this stays disabled (and the
 *  chip stays hidden) for everyone else - no wasted 403. Fails soft: an
 *  error yields an empty index. */
export function useCredentialIndex(): Map<string, number> {
  const { user } = useAuth();
  const enabled = Boolean(user?.is_superuser);

  const query = useQuery({
    queryKey: ["credentials", "index"],
    queryFn: () => getCredentials({}),
    enabled,
    staleTime: 60_000,
    retry: false,
  });

  const index = new Map<string, number>();
  for (const credential of query.data?.data ?? []) {
    const key = normalizeHostKey(credential.host);
    if (!key) continue;
    index.set(key, (index.get(key) ?? 0) + 1);
  }
  return index;
}
