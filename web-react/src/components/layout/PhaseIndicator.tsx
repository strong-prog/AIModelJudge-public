const PHASES = [
  { key: "analyze", label: "Анализ", color: "var(--accent)" },
  { key: "consult", label: "Консультация", color: "var(--green)" },
  { key: "synthesize", label: "Синтез", color: "var(--warning)" },
  { key: "apply", label: "Применение", color: "var(--purple)" },
];

interface PhaseIndicatorProps {
  currentPhase: string | null;
}

export function PhaseIndicator({ currentPhase }: PhaseIndicatorProps) {
  const currentIdx = PHASES.findIndex((p) => p.key === currentPhase);

  return (
    <div className="phase-indicators">
      {PHASES.map((p, i) => {
        const done = i < currentIdx;
        const isCurrent = i === currentIdx;
        const pending = i > currentIdx && currentIdx >= 0;

        return (
          <div
            key={p.key}
            title={p.label}
            className={`phase${isCurrent ? " active" : ""}${done ? " done" : ""}`}
            style={{ opacity: pending ? 0.35 : 1 }}
          >
            <span
              className={isCurrent ? "animate-phase-pulse" : ""}
              style={{
                display: "inline-flex",
                width: "8px",
                height: "8px",
                borderRadius: "50%",
                background: done ? p.color : isCurrent ? p.color : "var(--border)",
                flexShrink: 0,
              }}
            />
            {done ? "✓" : "◉"} {p.label}
          </div>
        );
      })}
    </div>
  );
}
