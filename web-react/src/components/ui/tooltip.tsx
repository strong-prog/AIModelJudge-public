import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface TooltipProps {
  content: string;
  children: ReactNode;
  className?: string;
}

export function Tooltip({ content, children, className }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  return (
    <span
      className={cn("amj-tooltip-wrapper")}
      style={{ position: "relative", display: "inline-flex" }}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
    >
      {children}
      {visible && (
        <span
          className={cn("amj-tooltip", className)}
          style={{
            position: "absolute",
            bottom: "calc(100% + 6px)",
            left: "50%",
            transform: "translateX(-50%)",
            background: "var(--card)",
            color: "var(--text-bright)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            padding: "4px 8px",
            fontSize: "0.7rem",
            whiteSpace: "nowrap",
            zIndex: 1100,
            pointerEvents: "none",
            boxShadow: "var(--shadow)",
          }}
        >
          {content}
        </span>
      )}
    </span>
  );
}
