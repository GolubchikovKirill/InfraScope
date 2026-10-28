import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function Login() {
  const { user, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
    } catch {
      setError("Неверный email или пароль");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <h1 className="app-wordmark text-[2.75rem] text-[var(--brand)]">
            RegStaer<span className="app-wordmark-suffix">-M</span>
          </h1>
          <span className="app-wordmark-product mt-3 text-[var(--text-muted)]!">
            InfraScope · мониторинг магазинов
          </span>
        </div>

        <form
          onSubmit={handleSubmit}
          className="app-panel p-6 space-y-5"
        >
          <h2 className="font-display text-2xl text-center text-[var(--text-strong)]">
            Вход в систему
          </h2>

          {error && (
            <div className="rounded-lg bg-[var(--danger-bg)] border border-[var(--danger-border)] px-4 py-3 text-sm text-[var(--danger-fg)]">
              {error}
            </div>
          )}

          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="app-input w-full px-4 py-2 text-sm"
              placeholder="admin@infrascope.dev"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700">Пароль</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="app-input w-full px-4 py-2 text-sm"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="app-btn-primary w-full px-4 py-2.5 text-sm disabled:opacity-50 transition"
          >
            {loading ? "Вход..." : "Войти"}
          </button>
        </form>
      </div>
    </div>
  );
}
