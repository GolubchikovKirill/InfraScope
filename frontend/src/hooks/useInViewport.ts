import { useEffect, useState, type RefObject } from "react";

/**
 * Whether the element is on (or near) the screen. Live widgets use it to stop
 * polling while scrolled away. Without IntersectionObserver (old browsers,
 * jsdom) it reports visible, so nothing silently stops updating.
 */
export function useInViewport<T extends Element>(ref: RefObject<T | null>, rootMargin = "200px"): boolean {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { rootMargin });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, rootMargin]);

  return visible;
}
