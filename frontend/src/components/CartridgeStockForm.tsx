import { useState, type FormEvent } from "react";
import { X, AlertCircle } from "lucide-react";
import type { CartridgeStock, CartridgeStockInput } from "../client";

const COLORS: { value: string; label: string }[] = [
  { value: "black", label: "Чёрный (K)" },
  { value: "cyan", label: "Голубой (C)" },
  { value: "magenta", label: "Пурпурный (M)" },
  { value: "yellow", label: "Жёлтый (Y)" },
  { value: "", label: "Без цвета" },
];

interface Props {
  stock?: CartridgeStock | null;
  onSave: (data: CartridgeStockInput & { cartridge_name: string }) => void;
  onClose: () => void;
  loading: boolean;
  error?: string | null;
}

export default function CartridgeStockForm({ stock, onSave, onClose, loading, error }: Props) {
  const [name, setName] = useState(stock?.cartridge_name ?? "");
  const [color, setColor] = useState(stock?.toner_color ?? "black");
  const [models, setModels] = useState(stock?.compatible_printer_models ?? "");
  const [quantity, setQuantity] = useState(String(stock?.quantity_on_hand ?? 0));
  const [minimum, setMinimum] = useState(String(stock?.minimum_stock ?? 0));
  const [isActive, setIsActive] = useState(stock?.is_active ?? true);
  const [note, setNote] = useState("");

  const nextQuantity = Math.max(0, Number.parseInt(quantity || "0", 10) || 0);
  const quantityChanged = stock ? nextQuantity !== stock.quantity_on_hand : nextQuantity > 0;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSave({
      cartridge_name: name.trim(),
      toner_color: color === "" ? null : color,
      compatible_printer_models: models.trim(),
      quantity_on_hand: nextQuantity,
      minimum_stock: Math.max(0, Number.parseInt(minimum || "0", 10) || 0),
      is_active: isActive,
      note: note.trim() || undefined,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-lg font-semibold text-gray-900">
            {stock ? "Карточка картриджа" : "Добавить картридж"}
          </h3>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-gray-100 transition" aria-label="Закрыть">
            <X className="h-5 w-5 text-gray-500" />
          </button>
        </div>

        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-lg bg-[var(--danger-bg)] border border-[var(--danger-border)] px-3 py-2.5 text-sm text-[var(--danger-fg)]">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="cartridge-name" className="block text-sm font-medium text-gray-700">
              Название / артикул
            </label>
            <input
              id="cartridge-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={128}
              className="app-input w-full px-3 py-2 text-sm"
              placeholder="Например: Hi-Black · BCR-CC530A [K]"
            />
            <p className="text-xs text-gray-500">
              Бренд и артикул пишутся одной строкой — так же, как позиция называется на складе.
            </p>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="cartridge-color" className="block text-sm font-medium text-gray-700">
              Цвет
            </label>
            <select
              id="cartridge-color"
              value={color ?? ""}
              onChange={(e) => setColor(e.target.value)}
              className="app-input w-full px-3 py-2 text-sm"
            >
              {COLORS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="cartridge-models" className="block text-sm font-medium text-gray-700">
              Совместимые принтеры
            </label>
            <textarea
              id="cartridge-models"
              value={models}
              onChange={(e) => setModels(e.target.value)}
              rows={3}
              maxLength={1024}
              className="app-input w-full px-3 py-2 text-sm"
              placeholder="HP Color LaserJet CM2320, CP2025"
            />
            <p className="text-xs text-gray-500">
              Модели через запятую — как они записаны в карточках принтеров.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label htmlFor="cartridge-qty" className="block text-sm font-medium text-gray-700">
                Остаток, шт.
              </label>
              <input
                id="cartridge-qty"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                inputMode="numeric"
                className="app-input w-full px-3 py-2 text-sm tabular-nums"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="cartridge-min" className="block text-sm font-medium text-gray-700">
                Минимум, шт.
              </label>
              <input
                id="cartridge-min"
                value={minimum}
                onChange={(e) => setMinimum(e.target.value)}
                inputMode="numeric"
                className="app-input w-full px-3 py-2 text-sm tabular-nums"
              />
            </div>
          </div>

          {quantityChanged && (
            <div className="space-y-1.5">
              <label htmlFor="cartridge-note" className="block text-sm font-medium text-gray-700">
                Причина изменения остатка
              </label>
              <input
                id="cartridge-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={512}
                className="app-input w-full px-3 py-2 text-sm"
                placeholder="Например: инвентаризация 18.08.2026"
              />
              <p className="text-xs text-gray-500">Попадёт в историю движений по этой позиции.</p>
            </div>
          )}

          {stock && (
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="size-4 rounded border-gray-300"
              />
              Позиция активна (снимите — уйдёт в архив, история сохранится)
            </label>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={loading || !name.trim()}
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {loading ? "Сохранение..." : "Сохранить"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
