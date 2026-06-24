import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Markdown } from "@/components/shared/Markdown";

interface ThinkingBlockProps {
  text: string;
}

export function ThinkingBlock({ text }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(false);

  if (!text) return null;

  return (
    <div
      className="thinking-block"
      style={{ margin: "8px 0" }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "6px",
          width: "100%",
          padding: "8px 12px",
          background: "transparent",
          border: "none",
          color: "var(--muted)",
          fontFamily: "inherit",
          fontSize: "0.78rem",
          cursor: "pointer",
          transition: "color var(--transition-fast)",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "var(--accent)")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "var(--muted)")}
      >
        {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <span className="tb-label">Thinking</span>
      </button>
      {expanded && (
        <div style={{ padding: "10px 14px", borderTop: "1px solid var(--thinking-border)" }}>
          <Markdown text={text} compact />
        </div>
      )}
    </div>
  );
}
