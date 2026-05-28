import { ArrowLeft, Compass } from "lucide-react";
import { useNavigate } from "react-router-dom";

export default function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="app-panel w-full max-w-xl p-8 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-rose-600 to-red-700 text-white shadow-lg">
          <Compass className="h-7 w-7" />
        </div>
        <div className="text-xs font-semibold uppercase tracking-[0.2em] text-rose-500">Error 404</div>
        <h1 className="mt-2 text-3xl font-semibold text-slate-900">Страница не найдена</h1>
        <p className="mt-2 text-sm text-slate-500">
          Возможно, ссылка устарела или адрес введен с ошибкой.
        </p>
        <div className="mt-6 flex items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="app-btn-secondary inline-flex items-center gap-2 px-4 py-2 text-sm"
          >
            <ArrowLeft className="h-4 w-4" />
            Назад
          </button>
          <button
            type="button"
            onClick={() => navigate("/")}
            className="app-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm"
          >
            На главную
          </button>
        </div>
      </div>
    </div>
  );
}
