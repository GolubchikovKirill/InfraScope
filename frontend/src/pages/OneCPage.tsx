import { useState } from "react";
import { Plane, QrCode } from "lucide-react";
import BoardingPassPanel from "../components/BoardingPassPanel";
import OneCQrPanel from "../components/OneCQrPanel";
import { SectionCard } from "../components/ui/AsyncState";

type Tab = "qr" | "boarding";

export default function OneCPage() {
  const [tab, setTab] = useState<Tab>("qr");

  return (
    <div className="space-y-6">
      <div className="app-panel p-3">
        <div className="app-tabbar flex gap-1 p-1.5 w-fit max-w-full overflow-x-auto app-compact-scroll">
          <button
            type="button"
            onClick={() => setTab("qr")}
            className={`app-tab inline-flex items-center gap-2 px-4 py-2 text-sm font-medium ${tab === "qr" ? "active" : "text-gray-500 hover:text-gray-700"}`}
          >
            <QrCode className="h-4 w-4" />
            Штрихкоды кассиров
          </button>
          <button
            type="button"
            onClick={() => setTab("boarding")}
            className={`app-tab inline-flex items-center gap-2 px-4 py-2 text-sm font-medium ${tab === "boarding" ? "active" : "text-gray-500 hover:text-gray-700"}`}
          >
            <Plane className="h-4 w-4" />
            Посадочные
          </button>
        </div>
      </div>

      {tab === "qr" ? (
        <SectionCard>
          <OneCQrPanel />
        </SectionCard>
      ) : (
        <SectionCard>
          <BoardingPassPanel />
        </SectionCard>
      )}
    </div>
  );
}
