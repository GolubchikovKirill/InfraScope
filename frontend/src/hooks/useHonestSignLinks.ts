import { useMemo } from "react";
import { useQuery, type QueryClient } from "@tanstack/react-query";
import {
  getHonestSignCashRegisters,
  type HonestSignCashRegisterLink,
  type HonestSignCashRegistersResponse,
  type HonestSignStatus,
} from "../client";

export const HONEST_SIGN_LINKS_KEY = ["honest-sign", "cash-registers"] as const;

/** Put freshly checked statuses into the cached links, matched by the target's
 *  original host (stable across IP overrides), without refetching. */
export function patchHonestSignStatuses(queryClient: QueryClient, statuses: HonestSignStatus[]) {
  const byOriginal = new Map(statuses.map((status) => [status.original_host, status]));
  queryClient.setQueryData<HonestSignCashRegistersResponse>(HONEST_SIGN_LINKS_KEY, (current) => {
    if (!current) return current;
    return {
      ...current,
      data: current.data.map((link) => {
        const status = byOriginal.get(link.target.original_host);
        return status ? { ...link, status } : link;
      }),
    };
  });
}

/** Which Honest Sign target (and last stored status) belongs to which cash
 *  register, read once for the whole list. Re-read every minute so the
 *  background check's results show up without a reload. Fails soft: without
 *  it the cards simply have no Honest Sign block. */
export function useHonestSignLinks() {
  const query = useQuery({
    queryKey: HONEST_SIGN_LINKS_KEY,
    queryFn: getHonestSignCashRegisters,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: false,
  });
  const byCashId = useMemo(() => {
    const map = new Map<string, HonestSignCashRegisterLink>();
    for (const link of query.data?.data ?? []) map.set(link.cash_register_id, link);
    return map;
  }, [query.data]);
  return { meta: query.data, byCashId, isLoading: query.isLoading };
}
