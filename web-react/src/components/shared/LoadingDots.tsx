export function LoadingDots() {
  return (
    <span
      style={{
        display: "inline-flex",
        gap: "3px",
        alignItems: "center",
        padding: "2px 0",
      }}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: "5px",
            height: "5px",
            borderRadius: "50%",
            background: "var(--muted)",
            animation: "pulse 1.4s ease-in-out infinite",
            animationDelay: `${i * 0.15}s`,
          }}
        />
      ))}
    </span>
  );
}
