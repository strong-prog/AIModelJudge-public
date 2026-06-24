import { useEffect, useState } from "react";
import { X } from "lucide-react";

interface FilePopupProps {
  path: string;
  onClose: () => void;
}

export function FilePopup({ path, onClose }: FilePopupProps) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const res = await fetch(`/upload?path=${encodeURIComponent(path)}`, {
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`${res.status}`);
        const text = await res.text();
        setContent(text);
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Failed to load");
      }
    }
    load();
    return () => controller.abort();
  }, [path]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1050,
        background: "var(--overlay)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          background: "var(--card)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-lg)",
          maxWidth: "85vw",
          maxHeight: "80vh",
          width: "700px",
          display: "flex",
          flexDirection: "column",
          boxShadow: "var(--shadow)",
          backdropFilter: "blur(var(--backdrop-blur))",
          animation: "slideUp 0.25s ease",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "10px 14px",
            borderBottom: "1px solid var(--border)",
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: "0.78rem", color: "var(--text-bright)", fontFamily: "monospace" }}>
            {path}
          </span>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              color: "var(--muted)",
              cursor: "pointer",
              padding: "4px",
              display: "flex",
              borderRadius: "var(--radius-sm)",
            }}
          >
            <X size={16} />
          </button>
        </div>
        <div
          style={{
            padding: "14px",
            overflow: "auto",
            flex: 1,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: "0.75rem",
            lineHeight: 1.5,
            whiteSpace: "pre-wrap",
            color: "var(--text)",
          }}
        >
          {error ? (
            <span style={{ color: "var(--danger)" }}>Error: {error}</span>
          ) : content === null ? (
            <span style={{ color: "var(--muted)" }}>Loading...</span>
          ) : (
            content
          )}
        </div>
      </div>
    </div>
  );
}
