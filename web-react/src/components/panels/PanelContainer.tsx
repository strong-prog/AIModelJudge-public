import { type ReactNode } from "react";
import { useAppContext } from "@/context/AppContext";
import { PanelTools } from "./PanelTools";
import { ErrorBoundary } from "./ErrorBoundary";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { Minimize2, X, Maximize2 } from "lucide-react";
import type { PanelState } from "@/types/models";

interface PanelContainerProps {
  panel: "left" | "right";
  modelName: string;
  children: ReactNode;
}

export function PanelContainer({ panel, modelName, children }: PanelContainerProps) {
  const { state, dispatch } = useAppContext();
  const panelState = panel === "left" ? state.panelLeftState : state.panelRightState;

  const setPanelState = (s: PanelState) => {
    dispatch({
      type: panel === "left" ? "SET_PANEL_LEFT" : "SET_PANEL_RIGHT",
      state: s,
    });
  };

  if (panelState === "closed") return null;

  const isMinimized = panelState === "minimized";

  return (
    <div
      className="panel"
      style={{
        width: isMinimized ? "40px" : "260px",
        minWidth: isMinimized ? "40px" : "200px",
        maxWidth: isMinimized ? "40px" : "400px",
        flexShrink: 0,
        transition: "width var(--transition)",
        borderRadius: isMinimized ? "var(--radius-sm)" : "var(--radius-lg)",
        boxShadow: isMinimized ? "none" : undefined,
      }}
    >
      {/* Header */}
      <div className="panel-header">
        {!isMinimized && (
          <span className="panel-title">{modelName}</span>
        )}
        <div style={{ display: "flex", gap: "2px" }}>
          <Tooltip content={isMinimized ? "Развернуть" : "Свернуть"}>
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                setPanelState(isMinimized ? "open" : "minimized")
              }
            >
              {isMinimized ? <Maximize2 size={14} /> : <Minimize2 size={14} />}
            </Button>
          </Tooltip>
          <Tooltip content="Закрыть панель">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setPanelState("closed")}
            >
              <X size={14} />
            </Button>
          </Tooltip>
        </div>
      </div>

      {/* Tools toggle */}
      {!isMinimized && <PanelTools panel={panel} />}

      {/* Content */}
      {!isMinimized && (
        <ErrorBoundary>
          <div className="panel-body" style={{ padding: "12px" }}>
            {children}
          </div>
        </ErrorBoundary>
      )}
    </div>
  );
}
