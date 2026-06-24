import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { postDiff } from "@/lib/api";
import type { DiffResponse } from "@/types/api";

interface DiffViewerProps {
  path: string;
  oldContent: string;
  newContent: string;
  onClose: () => void;
}

export function DiffViewer({ path, oldContent, newContent, onClose }: DiffViewerProps) {
  const [data, setData] = useState<DiffResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    postDiff({ file_path: path, old_content: oldContent, new_content: newContent })
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Diff failed"));
  }, [path, oldContent, newContent]);

  return (
    <div
      className="diff-viewer-overlay"
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
          maxWidth: "88vw",
          maxHeight: "85vh",
          width: "820px",
          display: "flex",
          flexDirection: "column",
          boxShadow: "var(--shadow)",
        }}
      >
        {/* Header */}
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
            Diff: {path}
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

        {/* Diff body */}
        <div
          className="diff-viewer-body"
          style={{
            padding: "0",
            overflow: "auto",
            flex: 1,
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            fontSize: "0.72rem",
            lineHeight: 1.55,
            background: "#0d1117",
            color: "var(--text)",
          }}
        >
          {error ? (
            <div style={{ padding: "20px", color: "var(--danger)" }}>Error: {error}</div>
          ) : !data ? (
            <div style={{ padding: "20px", color: "var(--muted)" }}>Loading...</div>
          ) : data.hunks.length === 0 ? (
            <div style={{ padding: "20px", color: "var(--muted)" }}>No changes</div>
          ) : (
            <div className="diff-viewer-lines" style={{ padding: "8px 0" }}>
              {data.hunks.map((hunk, hi) => (
                <div key={hi}>
                  <div className="diff-header">{hunk.header}</div>
                  {hunk.lines.map((line, li) => (
                    <div
                      key={li}
                      className={`diff-line diff-${line.type}`}
                    >
                      <span className="diff-line-prefix">
                        {line.type === "add" ? "+" : line.type === "remove" ? "-" : " "}
                      </span>
                      <span>{line.content.slice(1)}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer stats */}
        {data && data.hunks.length > 0 && (
          <div
            style={{
              display: "flex",
              gap: "12px",
              padding: "8px 14px",
              borderTop: "1px solid var(--border)",
              flexShrink: 0,
              fontSize: "0.65rem",
              color: "var(--muted)",
            }}
          >
            {(() => {
              let adds = 0, rems = 0;
              data.hunks.forEach((h) => h.lines.forEach((l) => {
                if (l.type === "add") adds++;
                else if (l.type === "remove") rems++;
              }));
              return (
                <>
                  <span style={{ color: "var(--green)" }}>+{adds}</span>
                  <span style={{ color: "var(--danger)" }}>-{rems}</span>
                  <span>{adds + rems} changes</span>
                </>
              );
            })()}
          </div>
        )}
      </div>
    </div>
  );
}
