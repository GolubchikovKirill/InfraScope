import { ArrowRightLeft, CheckCircle2 } from "lucide-react";

/**
 * Shared by NetworkScanner and NetworkDiscoveryModal - both had this exact
 * three-way badge duplicated with slightly different colour classes.
 */
export default function DiscoveryStatusBadge({ ipChanged, isKnown }: { ipChanged: boolean; isKnown: boolean }) {
  if (ipChanged) {
    return (
      <span className="app-status" style={{ color: "var(--warn-fg)", background: "var(--warn-bg)", borderColor: "var(--warn-border)" }}>
        <ArrowRightLeft className="h-3 w-3" />
        IP сменился
      </span>
    );
  }
  if (isKnown) {
    return (
      <span className="app-status app-status-ok">
        <CheckCircle2 className="h-3 w-3" />
        Известен
      </span>
    );
  }
  return (
    <span className="app-status" style={{ color: "var(--brand)", background: "var(--brand-soft)", borderColor: "var(--brand-border)" }}>
      Новый
    </span>
  );
}
