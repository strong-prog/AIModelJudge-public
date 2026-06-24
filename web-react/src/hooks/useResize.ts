import { useCallback, useRef, useState } from "react";

interface UseResizeOptions {
  defaultSize: number;
  minSize: number;
  maxSize: number;
  onResize?: (size: number) => void;
}

export function useResize({ defaultSize, minSize, maxSize, onResize }: UseResizeOptions) {
  const [size, setSize] = useState(defaultSize);
  const startXRef = useRef(0);
  const startSizeRef = useRef(defaultSize);
  const activeRef = useRef(false);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      activeRef.current = true;
      startXRef.current = e.clientX;
      startSizeRef.current = size;

      const onMouseMove = (me: MouseEvent) => {
        if (!activeRef.current) return;
        const delta = me.clientX - startXRef.current;
        const newSize = Math.max(minSize, Math.min(maxSize, startSizeRef.current + delta));
        setSize(newSize);
        onResize?.(newSize);
      };

      const onMouseUp = () => {
        activeRef.current = false;
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    },
    [size, minSize, maxSize, onResize]
  );

  return { size, setSize, onMouseDown };
}
