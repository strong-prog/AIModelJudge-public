import { cn } from "@/lib/utils";

interface ProgressProps {
  value: number; // 0–100
  className?: string;
}

export function Progress({ value, className }: ProgressProps) {
  const container: React.CSSProperties = {
    width: "100%",
    height: "8px",
    background: "var(--border)",
    borderRadius: "4px",
    overflow: "hidden",
  };
  const bar: React.CSSProperties = {
    height: "100%",
    width: `${Math.min(100, Math.max(0, value))}%`,
    background: value > 90 ? "var(--danger)" : value > 70 ? "var(--tool-icon)" : "var(--green)",
    borderRadius: "4px",
    transition: "width 0.3s ease",
  };
  return (
    <div className={cn("amj-progress", className)} style={container}>
      <div style={bar} />
    </div>
  );
}
