import OneCQrPanel from "../components/OneCQrPanel";
import { SectionCard } from "../components/ui/AsyncState";

export default function QrGeneratorPage() {
  return (
    <div className="space-y-6">
      <div className="app-toolbar app-page-toolbar p-4 sm:p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="app-toolbar-title">
          <h1 className="text-2xl font-bold text-slate-900">QR генератор</h1>
          <p className="text-sm text-slate-500 mt-1">
            Выгрузка QR-кодов кассиров из 1С (MOL/MOLEXT) в Word-документы
          </p>
        </div>
      </div>

      <SectionCard>
        <OneCQrPanel />
      </SectionCard>
    </div>
  );
}
