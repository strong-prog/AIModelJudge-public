import { Toggle } from "@/components/ui/toggle";
import { useAppContext } from "@/context/AppContext";

interface PanelToolsProps {
  panel: "left" | "right";
}

export function PanelTools({ panel }: PanelToolsProps) {
  const { state, dispatch } = useAppContext();
  const enabled = state.sideToolsEnabled[panel];

  return (
    <div style={{ display: "flex", gap: "4px", padding: "4px 8px" }}>
      <Toggle
        pressed={enabled}
        onPressedChange={(v) => dispatch({ type: "SET_SIDE_TOOLS", panel, enabled: v })}
      >
        CG
      </Toggle>
      <Toggle
        pressed={enabled}
        onPressedChange={(v) => dispatch({ type: "SET_SIDE_TOOLS", panel, enabled: v })}
      >
        Mem
      </Toggle>
    </div>
  );
}
