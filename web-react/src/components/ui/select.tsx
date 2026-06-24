import { type SelectHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  options: SelectOption[];
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, style, options, ...props }, ref) => {
    const base: React.CSSProperties = {
      background: "var(--bg)",
      color: "var(--text)",
      border: "1px solid var(--border)",
      borderRadius: "5px",
      padding: "6px 10px",
      fontFamily: "inherit",
      fontSize: "0.8rem",
      outline: "none",
      cursor: "pointer",
      minWidth: "120px",
    };
    return (
      <select ref={ref} className={cn("amj-select", className)} style={{ ...base, ...style }} {...props}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  }
);
Select.displayName = "Select";
