import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/** Mirrors one URL search param into state shaped like useState<string>, so
 *  swapping `useState("")` for this is a one-line change. Lets a filtered
 *  list page be linked to, shared, and restored with the browser's back
 *  button - see lib/deviceLinks for the links that rely on it. */
export function useQueryParamState(key: string, initial = ""): [string, (value: string) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const value = searchParams.get(key) ?? initial;

  const setValue = useCallback(
    (next: string) => {
      setSearchParams(
        (prev) => {
          const merged = new URLSearchParams(prev);
          if (next) merged.set(key, next);
          else merged.delete(key);
          return merged;
        },
        { replace: true },
      );
    },
    [key, setSearchParams],
  );

  return [value, setValue];
}
