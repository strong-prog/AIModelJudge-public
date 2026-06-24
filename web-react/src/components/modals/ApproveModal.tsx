import { Dialog, DialogBody, DialogClose, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { useAppContext } from "@/context/AppContext";

function formatIntent(toolName: string, input: Record<string, unknown>): string {
  switch (toolName) {
    case "bash": {
      const cmd = input.command || input.cmd || "";
      return String(cmd).slice(0, 300);
    }
    case "write_file": {
      const fp = input.file_path || input.path || "?";
      const content = input.content ? String(input.content).slice(0, 200) : "";
      return `${fp}${content ? "\n\n" + content + (String(input.content).length > 200 ? "…" : "") : ""}`;
    }
    case "edit_file": {
      const fp = input.file_path || input.path || "?";
      const old = input.old_string ? "Замена: " + String(input.old_string).slice(0, 100) : "";
      const nw = input.new_string ? " → " + String(input.new_string).slice(0, 100) : "";
      return `${fp}\n${old}${nw}`;
    }
    case "web_search": {
      const q = input.query || input.q || "";
      return String(q).slice(0, 300);
    }
    case "web_fetch": {
      const url = input.url || "";
      return String(url).slice(0, 300);
    }
    case "grep":
    case "glob":
    case "codegraph_search":
    case "codegraph_explore": {
      const q = input.pattern || input.query || input.symbol || "";
      return String(q).slice(0, 300);
    }
    case "read_file": {
      return String(input.file_path || input.path || "").slice(0, 300);
    }
    case "memory_recall":
    case "memory_remember": {
      return String(input.query || input.content || "").slice(0, 300);
    }
    default: {
      // Show first meaningful string value
      for (const key of ["file_path", "path", "query", "pattern", "command", "url", "content", "task"]) {
        const v = input[key];
        if (typeof v === "string" && v) return v.slice(0, 300);
      }
      return JSON.stringify(input, null, 2).slice(0, 500);
    }
  }
}

const TOOL_ICONS: Record<string, string> = {
  bash: "\u{1F4BB}", write_file: "\u{1F4DD}", edit_file: "\u{270F}\u{FE0F}",
  read_file: "\u{1F4C4}", glob: "\u{1F50D}", grep: "\u{1F50E}",
  web_search: "\u{1F310}", web_fetch: "\u{1F4E1}",
  codegraph_explore: "\u{1F9E0}", codegraph_search: "\u{1F9E0}",
  codegraph_node: "\u{1F9E0}", codegraph_callers: "\u{1F9E0}",
  memory_recall: "\u{1F9E0}", memory_remember: "\u{1F4BE}",
  agent: "\u{1F916}", task: "\u{1F4CB}",
};

export function ApproveModal() {
  const { state } = useAppContext();
  const { pendingConfirm, confirmResolver } = state;

  if (!pendingConfirm) return null;

  const handleDecision = (d: "approve" | "deny" | "allow_all") => {
    confirmResolver?.(d);
  };

  const label = pendingConfirm.label || pendingConfirm.tool_name;
  const icon = TOOL_ICONS[pendingConfirm.tool_name] || "\u{1F527}";
  const intent = formatIntent(pendingConfirm.tool_name, pendingConfirm.tool_input);

  return (
    <Dialog open={!!pendingConfirm} onClose={() => handleDecision("deny")}>
      <DialogHeader>
        <DialogTitle>Подтверждение инструмента</DialogTitle>
        <DialogClose onClick={() => handleDecision("deny")} />
      </DialogHeader>
      <DialogBody>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
          <span style={{ fontSize: "1.3rem" }}>{icon}</span>
          <span style={{ fontSize: "0.9rem", fontWeight: 600, color: "var(--text-heading)" }}>
            {label}
          </span>
        </div>
        <pre
          style={{
            padding: "12px 14px",
            background: "var(--bg)",
            borderRadius: "var(--radius-sm)",
            fontSize: "0.75rem",
            overflow: "auto",
            maxHeight: "260px",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            color: "var(--text)",
            border: "1px solid var(--border)",
            lineHeight: "1.5",
            margin: 0,
            fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
          }}
        >
          {intent}
        </pre>
      </DialogBody>
      <DialogFooter>
        <Tooltip content="Отклонить выполнение инструмента">
          <Button variant="ghost" onClick={() => handleDecision("deny")}>
            Отклонить
          </Button>
        </Tooltip>
        <Tooltip content="Разрешить все будущие вызовы инструментов в этой сессии">
          <Button variant="outline" onClick={() => handleDecision("allow_all")}>
            Разрешить все
          </Button>
        </Tooltip>
        <Tooltip content="Одобрить выполнение этого инструмента">
          <Button
            onClick={() => handleDecision("approve")}
            style={{ background: "var(--accent)", color: "var(--text-on-accent)", border: "none" }}
          >
            Одобрить
          </Button>
        </Tooltip>
      </DialogFooter>
    </Dialog>
  );
}
