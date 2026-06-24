import {
  useCallback,
  useEffect,
  useRef,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}

export function Dialog({ open, onClose, children, className }: DialogProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  const onKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose]
  );

  useEffect(() => {
    if (open) {
      document.addEventListener("keydown", onKeyDown);
      return () => document.removeEventListener("keydown", onKeyDown);
    }
  }, [open, onKeyDown]);

  if (!open) return null;

  const overlayStyle: React.CSSProperties = {
    position: "fixed",
    inset: 0,
    zIndex: 1000,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "var(--overlay)",
    animation: "fadeIn var(--transition-fast)",
  };

  const dialogStyle: React.CSSProperties = {
    background: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-lg)",
    boxShadow: "var(--shadow)",
    maxWidth: "90vw",
    maxHeight: "85vh",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
    animation: "slideUp var(--transition-normal)",
  };

  return (
    <div
      ref={overlayRef}
      className="modal-overlay"
      style={overlayStyle}
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
    >
      <div className={cn("amj-dialog", className)} style={dialogStyle}>
        {children}
      </div>
    </div>
  );
}

export function DialogHeader({ children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "16px 20px",
        borderBottom: "1px solid var(--border)",
        flexShrink: 0,
      }}
      {...props}
    >
      {children}
    </div>
  );
}

export function DialogTitle({
  children,
  ...props
}: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2 style={{ fontSize: "0.9rem", fontWeight: 500, color: "var(--text-bright)" }} {...props}>
      {children}
    </h2>
  );
}

export function DialogClose({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: "none",
        border: "none",
        color: "var(--muted)",
        cursor: "pointer",
        padding: "4px",
        borderRadius: "var(--radius-sm)",
        display: "flex",
      }}
    >
      <X size={18} />
    </button>
  );
}

export function DialogBody({ children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div style={{ padding: "20px", overflow: "auto", flex: 1 }} {...props}>
      {children}
    </div>
  );
}

export function DialogFooter({ children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "flex-end",
        gap: "8px",
        padding: "12px 20px",
        borderTop: "1px solid var(--border)",
        flexShrink: 0,
      }}
      {...props}
    >
      {children}
    </div>
  );
}
