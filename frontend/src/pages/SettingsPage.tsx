import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Save, Settings2 } from "lucide-react";
import { getGeneralSettings, getScannerSettings, updateGeneralSettings } from "../client";
import { EmptyState, ErrorState, FormActions, LoadingState, SectionCard } from "../components/ui/AsyncState";

type SettingsForm = {
  scan_subnet: string;
  scan_ports: string;
  dns_search_suffixes: string;
};

const emptyForm: SettingsForm = {
  scan_subnet: "",
  scan_ports: "",
  dns_search_suffixes: "",
};

export default function SettingsPage() {
  const [form, setForm] = useState<SettingsForm>(emptyForm);

  const { data: general, isLoading } = useQuery({
    queryKey: ["general-settings"],
    queryFn: getGeneralSettings,
  });

  const { data: scannerSettings } = useQuery({
    queryKey: ["scanner-settings"],
    queryFn: getScannerSettings,
  });

  useEffect(() => {
    if (!general) return;
    setForm(general);
  }, [general]);

  const saveMut = useMutation({
    mutationFn: updateGeneralSettings,
    onSuccess: (updated) => {
      setForm(updated);
    },
  });

  const submit = () => {
    saveMut.mutate(form);
  };

  return (
    <div className="space-y-6">
      <SectionCard className="space-y-4">
        <div className="flex items-center gap-2 text-slate-900">
          <Settings2 className="h-4 w-4" />
          <h2 className="text-base font-semibold">Сеть и сканирование</h2>
        </div>
        {isLoading ? (
          <LoadingState />
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Input
                label="Диапазон сети (CIDR, через запятую)"
                value={form.scan_subnet}
                onChange={(v) => setForm((s) => ({ ...s, scan_subnet: v }))}
              />
              <Input
                label="Порты сканирования (через запятую)"
                value={form.scan_ports}
                onChange={(v) => setForm((s) => ({ ...s, scan_ports: v }))}
              />
              <Input
                label="DNS search suffixes (через запятую)"
                value={form.dns_search_suffixes}
                onChange={(v) => setForm((s) => ({ ...s, dns_search_suffixes: v }))}
              />
            </div>
            <FormActions className="justify-end">
              <button
                onClick={submit}
                className="app-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm"
                disabled={saveMut.isPending}
              >
                <Save className="h-4 w-4" />
                {saveMut.isPending ? "Сохранение..." : "Сохранить"}
              </button>
            </FormActions>
            {saveMut.isError && <ErrorState text="Не удалось сохранить настройки. Проверьте корректность значений." />}
          </>
        )}
      </SectionCard>

      {scannerSettings ? (
        <SectionCard className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-900">Текущие системные лимиты сканера</h3>
          <div className="grid gap-1 text-xs text-gray-500 sm:grid-cols-2 lg:grid-cols-4">
            <div>max_hosts: {scannerSettings.max_hosts}</div>
            <div>tcp_timeout: {scannerSettings.tcp_timeout}</div>
            <div>tcp_retries: {scannerSettings.tcp_retries}</div>
            <div>tcp_concurrency: {scannerSettings.tcp_concurrency}</div>
          </div>
        </SectionCard>
      ) : (
        <EmptyState text="Системные лимиты сканера пока не доступны." />
      )}
    </div>
  );
}

function Input({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="text-sm">
      <span className="mb-1 block text-slate-600">{label}</span>
      <input className="app-input w-full py-2 px-3 text-sm" value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}
