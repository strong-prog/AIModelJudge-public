import { type HTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

const cardStyle: React.CSSProperties = {
  background: "var(--card)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border)",
  boxShadow: "var(--shadow)",
};

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, style, ...props }, ref) => (
    <div ref={ref} className={cn("amj-card", className)} style={{ ...cardStyle, ...style }} {...props} />
  )
);
Card.displayName = "Card";

export const CardHeader = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, style, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("amj-card-header", className)}
      style={{ padding: "14px 16px 0", ...style }}
      {...props}
    />
  )
);
CardHeader.displayName = "CardHeader";

export const CardTitle = forwardRef<HTMLHeadingElement, HTMLAttributes<HTMLHeadingElement>>(
  ({ className, style, ...props }, ref) => (
    <h3
      ref={ref}
      className={cn("amj-card-title", className)}
      style={{ fontSize: "0.85rem", fontWeight: 500, color: "var(--text-bright)", ...style }}
      {...props}
    />
  )
);
CardTitle.displayName = "CardTitle";

export const CardContent = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, style, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("amj-card-content", className)}
      style={{ padding: "14px 16px", ...style }}
      {...props}
    />
  )
);
CardContent.displayName = "CardContent";
