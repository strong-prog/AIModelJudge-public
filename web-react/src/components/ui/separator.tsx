import { cn } from "@/lib/utils";

interface SeparatorProps {
  orientation?: "horizontal" | "vertical";
  className?: string;
}

export function Separator({ orientation = "horizontal", className }: SeparatorProps) {
  const style: React.CSSProperties = {
    background: "var(--border)",
    ...(orientation === "horizontal"
      ? { width: "100%", height: "1px" }
      : { height: "100%", width: "1px" }),
  };
  return <div className={cn("amj-separator", className)} style={style} />;
}
