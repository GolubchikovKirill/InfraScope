import { useEffect, useState } from "react";

/** Re-evaluate expiry even when the server stops delivering observations. */
export function useObservationTime() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}
