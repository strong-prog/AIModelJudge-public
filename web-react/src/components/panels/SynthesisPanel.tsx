import { Markdown } from "@/components/shared/Markdown";

interface SynthesisSection {
  title: string;
  content: string;
  icon: string;
}

interface SynthesisPanelProps {
  sections: SynthesisSection[];
  streaming: boolean;
}

export function SynthesisPanel({ sections, streaming }: SynthesisPanelProps) {
  return (
    <div
      style={{
        flex: 1,
        overflow: "auto",
        padding: "12px",
      }}
    >
      {sections.length === 0 && !streaming && (
        <div
          style={{
            textAlign: "center",
            color: "var(--muted)",
            fontSize: "0.72rem",
            padding: "20px",
          }}
        >
          Синтез появится здесь на фазе 3
        </div>
      )}

      {sections.map((s, i) => (
        <div
          key={i}
          style={{
            marginBottom: "10px",
            padding: "12px",
            background: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-md)",
            boxShadow: "var(--shadow-card)",
          }}
        >
          <div
            style={{
              fontSize: "0.75rem",
              fontWeight: 500,
              color: "var(--text-bright)",
              marginBottom: "6px",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <span>{s.icon}</span>
            <span>{s.title}</span>
          </div>
          <div style={{ fontSize: "0.72rem" }}>
            <Markdown text={s.content} compact />
          </div>
        </div>
      ))}

      {streaming && sections.length === 0 && (
        <div style={{ textAlign: "center", color: "var(--accent)", fontSize: "0.72rem" }}>
          Синтезирую...
        </div>
      )}
    </div>
  );
}
