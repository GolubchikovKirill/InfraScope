import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Save, Settings2 } from "lucide-react";
import { getGeneralSettings, updateGeneralSettings } from "../client";
import { ErrorState, FormActions, LoadingState, SectionCard } from "../components/ui/AsyncState";

type SettingsForm = {
  dns_search_suffixes: string;
};

const emptyForm: SettingsForm = {
  dns_search_suffixes: "",
};

export default function SettingsPage() {
  const [form, setForm] = useState<SettingsForm>(emptyForm);

  const { data: general, isLoading } = useQuery({
    queryKey: ["general-settings"],
    queryFn: getGeneralSettings,
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
