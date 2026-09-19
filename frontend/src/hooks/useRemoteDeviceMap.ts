import { useQuery } from "@tanstack/react-query";
import { getRemoteDevices, type RemoteDevice } from "../client";

/** One cached fetch of every RustDesk endpoint, indexed by hostname.
 *  Shared by the device-card pages so each card can show its connect / deploy
 *  state without its own request. Fails soft: an error yields an empty map.
 *
 *  Entries taken out of management are included: the machine may well still be on the
 *  console (a till was found online with its entry removed), and its ID is all a
 *  connection needs. Callers tell them apart by `device.managed`. */
export function useRemoteDeviceMap() {
  const query = useQuery({
    queryKey: ["remote-devices", "map"],
    queryFn: () => getRemoteDevices({ include_unmanaged: true }),
    staleTime: 15000,
    refetchInterval: 30000,
    retry: false,
  });

  const map = new Map<string, RemoteDevice>();
  for (const d of query.data?.data ?? []) map.set(d.hostname, d);

  return { map, isLoading: query.isLoading, isError: query.isError };
}
