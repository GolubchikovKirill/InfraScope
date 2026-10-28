import React from "react";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  isLoading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className = "", variant = "primary", size = "md", isLoading, children, disabled, ...props }, ref) => {
    // The press feedback is CSS (active:scale) - it used to pull in framer-motion,
    // ~42 kB gzip on the first paint of every page, for this one tap animation.
    const baseClasses = "inline-flex active:scale-[0.98] items-center justify-center font-medium transition focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none";

    const variants = {
      primary: "app-btn-primary focus:ring-[var(--brand-ring)]",
      secondary: "app-btn-secondary focus:ring-slate-400",
      danger: "bg-[var(--danger-fg)] hover:brightness-90 text-white shadow-lg shadow-[var(--danger-fg)]/30 focus:ring-[var(--danger-fg)] rounded-xl",
      ghost: "hover:bg-slate-100 text-slate-700 rounded-xl",
    };

    const sizes = {
      sm: "h-9 px-4 text-sm",
      md: "h-10 px-6 text-sm",
      lg: "h-12 px-8 text-base",
    };

    return (
      <button
        ref={ref}
        className={`${baseClasses} ${variants[variant]} ${sizes[size]} ${className}`}
        disabled={disabled || isLoading}
        {...props}
      >
        {isLoading ? (
          <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
        ) : null}
        <>{children}</>
      </button>
    );
  }
);

Button.displayName = "Button";
