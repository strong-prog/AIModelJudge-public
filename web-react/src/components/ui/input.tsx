import { type InputHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, style, ...props }, ref) => {
    const base: React.CSSProperties = {
      background: "var(--bg)",
      color: "var(--text)",
      border: "1px solid var(--border)",
      borderRadius: "5px",
      padding: "6px 10px",
      fontFamily: "inherit",
      fontSize: "0.82rem",
      outline: "none",
      width: "100%",
    };
    return (
      <input ref={ref} className={cn("amj-input", className)} style={{ ...base, ...style }} {...props} />
    );
  }
);
Input.displayName = "Input";
