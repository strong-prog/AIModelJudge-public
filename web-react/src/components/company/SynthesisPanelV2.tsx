/**
 * SynthesisPanelV2 — Company Mode cross-domain synthesis.
 * Displays consensus, contradictions, gaps, priorities, and unified solution.
 */

interface SynthesisSection {
  title: string;
  icon: string;
  items: string[];
}

interface SynthesisPanelV2Props {
  sections: SynthesisSection[];
  streaming: boolean;
}

export function SynthesisPanelV2({ sections, streaming }: SynthesisPanelV2Props) {
  if (sections.length === 0) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          height: "100%",
          background: "var(--bg)",
          padding: "16px",
          color: "var(--text-muted)",
          fontSize: "0.78rem",
          fontStyle: "italic",
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: "8px", color: "var(--text-bright)", fontStyle: "normal" }}>
          Синтез Company Mode
        </div>
        Специалисты анализируют запрос. Когда ответы будут собраны, здесь появится кросс-доменный синтез.
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "var(--bg)",
        overflow: "auto",
        padding: "12px",
        gap: "10px",
      }}
    >
      <div
        style={{
          fontSize: "0.8rem",
          fontWeight: 600,
          color: "var(--text-bright)",
          borderBottom: "1px solid var(--border)",
          paddingBottom: "8px",
          display: "flex",
          alignItems: "center",
          gap: "6px",
        }}
      >
        <span>🧠</span>
        <span>Архитектор — синтез</span>
        {streaming && (
          <span
            style={{
              marginLeft: "auto",
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              background: "var(--accent)",
              animation: "pulse 1s infinite",
            }}
          />
        )}
      </div>

      {sections.map((section, i) => (
        <div
          key={i}
          style={{
            background: "var(--surface)",
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--border)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "6px 10px",
              fontSize: "0.72rem",
              fontWeight: 600,
              color: "var(--text-bright)",
              background: "var(--surface-hover)",
              borderBottom: "1px solid var(--border)",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <span>{section.icon}</span>
            <span>{section.title}</span>
            <span
              style={{
                marginLeft: "auto",
                fontSize: "0.65rem",
                color: "var(--text-muted)",
              }}
            >
              {section.items.length}
            </span>
          </div>
          <div style={{ padding: "6px 10px" }}>
            {section.items.map((item, j) => (
              <div
                key={j}
                style={{
                  fontSize: "0.7rem",
                  color: "var(--text-muted)",
                  padding: "3px 0",
                  lineHeight: 1.5,
                }}
              >
                <span style={{ color: "var(--accent)", marginRight: "4px" }}>•</span>
                {item}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
