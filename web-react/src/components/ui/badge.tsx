import { type HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type BadgeVariant = "default" | "accent" | "danger" | "green";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const variantColors: Record<BadgeVariant, { bg: string; fg: string }> = {
  default: { bg: "var(--border)", fg: "var(--text)" },
  accent: { bg: "var(--accent)", fg: "var(--text-on-accent)" },
  danger: { bg: "var(--danger)", fg: "var(--text-on-accent)" },
  green: { bg: "var(--green)", fg: "var(--text-on-accent)" },
};

export function Badge({ variant = "default", className, style, ...props }: BadgeProps) {
  const c = variantColors[variant];
  const base: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    padding: "1px 7px",
    borderRadius: "3px",
    fontSize: "0.68rem",
    fontWeight: 400,
    background: c.bg,
    color: c.fg,
    whiteSpace: "nowrap",
  };
  return (
    <span className={cn("amj-badge", className)} style={{ ...base, ...style }} {...props} />
  );
}
