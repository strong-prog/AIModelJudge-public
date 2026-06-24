import { useState } from "react";

interface ResizeHandleProps {
  orientation?: "horizontal" | "vertical";
  onMouseDown: (e: React.MouseEvent) => void;
}

export function ResizeHandle({ orientation = "horizontal", onMouseDown }: ResizeHandleProps) {
  const [dragging, setDragging] = useState(false);

  const isHorizontal = orientation === "horizontal";

  const style: React.CSSProperties = {
    width: isHorizontal ? "4px" : "100%",
    height: isHorizontal ? "100%" : "4px",
    cursor: isHorizontal ? "col-resize" : "row-resize",
    flexShrink: 0,
    zIndex: 10,
    background: dragging ? "var(--accent)" : "transparent",
    transition: dragging ? "none" : "background 0.15s",
  };

  return (
    <div
      style={style}
      className="amj-resize-handle"
      onMouseDown={(e) => {
        setDragging(true);
        onMouseDown(e);
      }}
      onMouseUp={() => setDragging(false)}
    />
  );
}
