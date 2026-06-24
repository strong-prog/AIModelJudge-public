import { Markdown } from "@/components/shared/Markdown";

interface PanelStreamProps {
  content: string;
  toolActivity?: Array<{
    tool_name: string;
    status: "running" | "done";
    result?: string;
  }>;
}

export function PanelStream({ content, toolActivity }: PanelStreamProps) {
  return (
    <div
      style={{
        flex: 1,
        overflow: "auto",
        padding: "12px",
        fontSize: "0.76rem",
        lineHeight: "var(--line-height)",
      }}
    >
      {/* Tool activity */}
      {toolActivity?.map((t, i) => (
        <div
          key={i}
          className="animate-fade-in-up"
          style={{
            padding: "6px 10px",
            marginBottom: "8px",
            background: "var(--card)",
            border: `1px solid ${t.status === "running" ? "var(--accent)" : "var(--border)"}`,
            borderRadius: "var(--radius-sm)",
            fontSize: "0.7rem",
            boxShadow: "var(--shadow-card)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ color: "var(--tool-icon)", fontWeight: 500 }}>{t.tool_name}</span>
            {t.status === "running" ? (
              <span style={{ color: "var(--accent)", fontSize: "0.62rem" }}>running...</span>
            ) : (
              <span style={{ color: "var(--green)", fontSize: "0.62rem", fontWeight: 500 }}>done ✓</span>
            )}
          </div>
          {t.result && (
            <div
              style={{
                marginTop: "6px",
                padding: "6px 8px",
                background: "var(--bg)",
                borderRadius: "var(--radius-sm)",
                maxHeight: "80px",
                overflow: "auto",
                whiteSpace: "pre-wrap",
                color: "var(--text)",
                fontSize: "0.68rem",
                borderLeft: "2px solid var(--green)",
              }}
            >
              {t.result.length > 200 ? t.result.slice(0, 200) + "..." : t.result}
            </div>
          )}
        </div>
      ))}

      {/* Text content */}
      {content && (
        <div className="animate-fade-in-up">
          <Markdown text={content} compact />
        </div>
      )}
    </div>
  );
}
