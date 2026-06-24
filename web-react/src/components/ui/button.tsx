import { type ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

type ButtonVariant = "default" | "ghost" | "outline" | "danger";
type ButtonSize = "sm" | "md" | "icon";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const variantStyles: Record<ButtonVariant, React.CSSProperties> = {
  default: {
    background: "var(--accent)",
    color: "var(--text-on-accent)",
    border: "none",
  },
  ghost: {
    background: "transparent",
    color: "var(--text)",
    border: "1px solid transparent",
  },
  outline: {
    background: "transparent",
    color: "var(--text)",
    border: "1px solid var(--border)",
  },
  danger: {
    background: "var(--danger)",
    color: "var(--text-on-accent)",
    border: "none",
  },
};

const sizeStyles: Record<ButtonSize, React.CSSProperties> = {
  sm: { padding: "4px 10px", fontSize: "0.75rem", height: "28px" },
  md: { padding: "6px 14px", fontSize: "0.8rem", height: "34px" },
  icon: { padding: "6px", fontSize: "0.85rem", width: "32px", height: "32px" },
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "default", size = "md", className, style, ...props }, ref) => {
    const base: React.CSSProperties = {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      gap: "6px",
      borderRadius: "var(--radius-sm)",
      fontFamily: "inherit",
      cursor: "pointer",
      transition: "all var(--transition-fast)",
      lineHeight: 1,
      fontWeight: 400,
    };
    return (
      <button
        ref={ref}
        className={cn("amj-button", className)}
        style={{ ...base, ...variantStyles[variant], ...sizeStyles[size], ...style }}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";
