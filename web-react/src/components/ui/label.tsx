import { type LabelHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

export const Label = forwardRef<HTMLLabelElement, LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, style, ...props }, ref) => {
    const base: React.CSSProperties = {
      fontSize: "0.78rem",
      color: "var(--muted)",
      fontWeight: 400,
      display: "block",
    };
    return (
      <label ref={ref} className={cn("amj-label", className)} style={{ ...base, ...style }} {...props} />
    );
  }
);
Label.displayName = "Label";
