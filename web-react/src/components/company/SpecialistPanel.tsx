import type { SpecialistRole, SpecialistEvent } from "@/types/models";

interface SpecialistPanelProps {
  specialist: SpecialistRole;
  displayName: string;
  events: SpecialistEvent[];
  streaming: boolean;
}

const roleIcons: Record<SpecialistRole, string> = {
  marketer: "📈",
  lawyer: "⚖",
  accountant: "💰",
  devops: "⚙",
};

export function SpecialistPanel({ specialist, displayName, events, streaming }: SpecialistPanelProps) {
  const icon = roleIcons[specialist] || "👤";
  const lastContent = events
    .filter((e) => e.type === "specialist.done" && e.content)
    .pop()?.content || "";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "var(--bg)",
        borderRadius: "var(--radius-sm)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "6px 10px",
          fontSize: "0.75rem",
          fontWeight: 600,
          color: "var(--text-bright)",
          background: "var(--surface-hover)",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          gap: "6px",
        }}
      >
        <span>{icon}</span>
        <span>{displayName}</span>
        {streaming && (
          <span style={{ marginLeft: "auto", width: "6px", height: "6px", borderRadius: "50%", background: "var(--accent)", animation: "pulse 1s infinite" }} />
        )}
      </div>

      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: "8px 10px",
          fontSize: "0.72rem",
          color: "var(--text-muted)",
          lineHeight: 1.5,
          whiteSpace: "pre-wrap",
        }}
      >
        {events.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontStyle: "italic" }}>
            Ожидание ответа...
          </div>
        ) : (
          <>
            {events.map((e, i) => (
              <div
                key={i}
                style={{
                  marginBottom: "8px",
                  padding: "4px 8px",
                  borderRadius: "4px",
                  background:
                    e.type === "specialist.done"
                      ? "var(--surface-hover)"
                      : e.type === "specialist.thinking"
                        ? "var(--bg)"
                        : "transparent",
                  border:
                    e.type === "specialist.done"
                      ? "1px solid var(--border)"
                      : "none",
                }}
              >
                {e.type === "specialist.thinking" && (
                  <span style={{ color: "var(--text-muted)" }}>
                    {e.phase === "analysis" ? "Анализирую вопрос..." : "Обрабатываю..."}
                  </span>
                )}
                {e.type === "specialist.done" && e.content && (
                  <span>{e.content}</span>
                )}
              </div>
            ))}
            {lastContent && (
              <div
                style={{
                  marginTop: "8px",
                  padding: "8px",
                  borderRadius: "4px",
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: "4px", fontSize: "0.7rem", color: "var(--accent)" }}>
                  Ответ:
                </div>
                <div style={{ whiteSpace: "pre-wrap" }}>{lastContent}</div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
