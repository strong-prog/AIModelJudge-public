import { useState } from "react";
import { Wrench, FileText, GitCompare } from "lucide-react";
import { FilePopup } from "./FilePopup";
import { DiffViewer } from "./DiffViewer";

// Module-level cache: file_path → content from read_file tool results
const fileReadCache = new Map<string, string>();

interface ToolCardProps {
  toolName: string;
  toolInput: Record<string, unknown>;
  isExecuting?: boolean;
  result?: string;
  compact?: boolean;
}

export function ToolCard({ toolName, toolInput, isExecuting, result, compact }: ToolCardProps) {
  const [viewFile, setViewFile] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [diffView, setDiffView] = useState<{ path: string; oldContent: string; newContent: string } | null>(null);

  const filePath = (toolInput?.file_path as string) || (toolInput?.path as string) || "";
  const toolLabel = toolName.replace(/_/g, " ");

  // Update file read cache when read_file result arrives
  if (result && toolName === "read_file" && filePath) {
    fileReadCache.set(filePath, result);
  }

  // Check if we have old content for diff
  const isEdit = toolName === "edit_file" || toolName === "write_file";
  const oldContent = isEdit && filePath ? fileReadCache.get(filePath) : undefined;

  return (
    <>
      <div
        className="tool-card"
        style={{
          margin: "8px 0",
          borderColor: isExecuting ? "var(--accent)" : undefined,
        }}
      >
        <div
          className="tc-header"
          onClick={() => setExpanded(!expanded)}
        >
          <Wrench size={12} style={{ color: "var(--tool-icon)", flexShrink: 0 }} />
          <span className="tc-name">{toolLabel}</span>
          {isExecuting && (
            <span className="tc-status">running...</span>
          )}
        </div>

        {filePath && (
          <div className="tc-path" style={{ display: "flex", gap: "6px", alignItems: "center" }}>
            <span
              onClick={(e) => {
                e.stopPropagation();
                setViewFile(filePath);
              }}
              style={{ display: "flex", alignItems: "center", gap: "4px", cursor: "pointer" }}
            >
              <FileText size={11} />
              <span style={{ textDecoration: "underline", textUnderlineOffset: "3px" }}>
                {filePath}
              </span>
            </span>
            {isEdit && result && oldContent && (
              <span
                onClick={(e) => {
                  e.stopPropagation();
                  setDiffView({ path: filePath, oldContent, newContent: result });
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "3px",
                  cursor: "pointer",
                  fontSize: "0.6rem",
                  color: "var(--accent)",
                }}
              >
                <GitCompare size={11} />
                Diff
              </span>
            )}
          </div>
        )}

        {expanded && !compact && (
          <pre style={{ marginTop: "6px", padding: "6px 8px", background: "var(--bg)", borderRadius: "3px", fontSize: "0.68rem", overflow: "auto", maxHeight: "120px", whiteSpace: "pre-wrap", wordBreak: "break-all", color: "var(--text)" }}>
            {JSON.stringify(toolInput, null, 2)}
          </pre>
        )}

        {result && (
          <div className="tc-result">
            {result.length > 500 ? result.slice(0, 500) + "..." : result}
          </div>
        )}
      </div>

      {viewFile && <FilePopup path={viewFile} onClose={() => setViewFile(null)} />}
      {diffView && (
        <DiffViewer
          path={diffView.path}
          oldContent={diffView.oldContent}
          newContent={diffView.newContent}
          onClose={() => setDiffView(null)}
        />
      )}
    </>
  );
}
