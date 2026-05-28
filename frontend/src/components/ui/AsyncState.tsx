import type { ReactNode } from "react";

type CommonProps = {
  className?: string;
};

export function LoadingState({ className = "", text = "Загрузка..." }: CommonProps & { text?: string }) {
  return <div className={`text-sm text-slate-500 ${className}`}>{text}</div>;
}

export function ErrorState({
  className = "",
  text = "Произошла ошибка. Попробуйте снова.",
}: CommonProps & { text?: string }) {
  return <div className={`text-sm text-rose-700 ${className}`}>{text}</div>;
}

export function EmptyState({
  className = "",
  text = "Данные отсутствуют.",
}: CommonProps & { text?: string }) {
  return <div className={`text-sm text-slate-500 ${className}`}>{text}</div>;
}

export function SectionCard({
  className = "",
  children,
}: CommonProps & {
  children: ReactNode;
}) {
  return <div className={`app-panel p-4 sm:p-5 ${className}`}>{children}</div>;
}

export function FormActions({
  className = "",
  children,
}: CommonProps & {
  children: ReactNode;
}) {
  return <div className={`flex flex-wrap items-center gap-2 ${className}`}>{children}</div>;
}
