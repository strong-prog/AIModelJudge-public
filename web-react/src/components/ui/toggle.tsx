import { cn } from "@/lib/utils";

interface ToggleProps {
  pressed: boolean;
  onPressedChange: (pressed: boolean) => void;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
}

export function Toggle({
  pressed,
  onPressedChange,
  children,
  className,
  disabled,
}: ToggleProps) {
  const base: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    padding: "4px 10px",
    borderRadius: "4px",
    border: "1px solid var(--border)",
    background: pressed ? "var(--accent)" : "transparent",
    color: pressed ? "var(--text-on-accent)" : "var(--text)",
    fontFamily: "inherit",
    fontSize: "0.75rem",
    cursor: disabled ? "default" : "pointer",
    opacity: disabled ? 0.5 : 1,
    transition: "all 0.15s",
  };
  return (
    <button
      className={cn("amj-toggle", className)}
      style={base}
      onClick={() => onPressedChange(!pressed)}
      disabled={disabled}
      aria-pressed={pressed}
    >
      {children}
    </button>
  );
}
