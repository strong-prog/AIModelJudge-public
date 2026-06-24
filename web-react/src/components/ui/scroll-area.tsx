import { type HTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

export const ScrollArea = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, style, ...props }, ref) => {
    const base: React.CSSProperties = {
      overflow: "auto",
      scrollbarWidth: "thin",
    };
    return (
      <div ref={ref} className={cn("amj-scroll-area", className)} style={{ ...base, ...style }} {...props} />
    );
  }
);
ScrollArea.displayName = "ScrollArea";
