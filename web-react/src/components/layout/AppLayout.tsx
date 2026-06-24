import { type ReactNode } from "react";

interface AppLayoutProps {
  nav: ReactNode;
  leftPanel?: ReactNode;
  chat: ReactNode;
  rightPanel?: ReactNode;
  onNavResize?: (e: React.MouseEvent) => void;
  onLeftResize?: (e: React.MouseEvent) => void;
  onRightResize?: (e: React.MouseEvent) => void;
}

export function AppLayout({
  nav,
  leftPanel,
  chat,
  rightPanel,
  onNavResize,
  onLeftResize,
  onRightResize,
}: AppLayoutProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        width: "100%",
        height: "100dvh",
        overflow: "hidden",
      }}
    >
      {/* Navigator panel */}
      {nav}

      {/* Nav resize handle */}
      {onNavResize && (
        <div
          className="amj-resize-handle"
          style={{
            width: "4px",
            cursor: "col-resize",
            flexShrink: 0,
            zIndex: 10,
            transition: "background 0.15s",
          }}
          onMouseDown={onNavResize}
        />
      )}

      {/* Left side panel */}
      {leftPanel}
      {onLeftResize && (
        <div
          className="amj-resize-handle"
          style={{
            width: "4px",
            cursor: "col-resize",
            flexShrink: 0,
            zIndex: 10,
            transition: "background 0.15s",
          }}
          onMouseDown={onLeftResize}
        />
      )}

      {/* Main chat area */}
      {chat}

      {/* Right side panel resize */}
      {onRightResize && (
        <div
          className="amj-resize-handle"
          style={{
            width: "4px",
            cursor: "col-resize",
            flexShrink: 0,
            zIndex: 10,
            transition: "background 0.15s",
          }}
          onMouseDown={onRightResize}
        />
      )}

      {/* Right side panel */}
      {rightPanel}
    </div>
  );
}
