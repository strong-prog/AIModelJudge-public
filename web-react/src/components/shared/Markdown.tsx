import { useMemo } from "react";
import { marked } from "marked";

interface MarkdownProps {
  text: string;
  compact?: boolean;
}

export function Markdown({ text, compact }: MarkdownProps) {
  const html = useMemo(() => {
    if (!text) return "";
    try {
      const result = marked.parse(text, { async: false }) as string;
      return result;
    } catch {
      return text;
    }
  }, [text]);

  return (
    <div
      className="amj-markdown"
      style={{
        fontSize: compact ? "0.78rem" : "0.82rem",
        lineHeight: "var(--line-height)",
        wordBreak: "break-word",
        overflowWrap: "break-word",
      }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
