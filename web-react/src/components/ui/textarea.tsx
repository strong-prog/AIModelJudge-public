import { type TextareaHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, style, ...props }, ref) => {
  const base: React.CSSProperties = {
    background: "var(--bg)",
    color: "var(--text)",
    border: "1px solid var(--border)",
    borderRadius: "6px",
    padding: "10px 12px",
    fontFamily: "inherit",
    fontSize: "0.82rem",
    resize: "none",
    outline: "none",
    width: "100%",
    lineHeight: 1.5,
  };
  return (
    <textarea
      ref={ref}
      className={cn("amj-textarea", className)}
      style={{ ...base, ...style }}
      {...props}
    />
  );
});
Textarea.displayName = "Textarea";
