import type { ChatMessage as ChatMessageType, SkillCandidate } from "@/types/models";
import { Markdown } from "@/components/shared/Markdown";
import { ThinkingBlock } from "./ThinkingBlock";
import { ToolCard } from "./ToolCard";
import { User, Bot, Save, Sparkles } from "lucide-react";

interface ChatMessageProps {
  message: ChatMessageType;
  onSaveSkill?: (content: string) => void;
  skillCandidate?: SkillCandidate | null;
  onSaveCandidate?: () => void;
}

export function ChatMessage({ message, onSaveSkill, skillCandidate, onSaveCandidate }: ChatMessageProps) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";

  const roleIcon = isUser ? (
    <User size={14} style={{ color: "var(--accent)" }} />
  ) : isAssistant ? (
    <Bot size={14} style={{ color: "var(--green)" }} />
  ) : null;

  const roleLabel =
    message.role === "user" ? "Вы" : message.role === "assistant" ? "Hermes" : message.role;

  return (
    <div
      className="animate-fade-in-up"
      style={{
        padding: "12px 16px",
        borderBottom: isAssistant ? "1px solid var(--border)" : "none",
      }}
    >
      {/* Role label */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          marginBottom: "8px",
        }}
      >
        {roleIcon}
        <span
          style={{
            fontSize: "0.72rem",
            fontWeight: 500,
            color: "var(--muted)",
            textTransform: "uppercase",
            letterSpacing: "0.05em",
          }}
        >
          {roleLabel}
        </span>
        {message.phase && (
          <span style={{ fontSize: "0.62rem", color: "var(--accent)", fontWeight: 500 }}>
            [{message.phase}]
          </span>
        )}
        {isAssistant && message.content && skillCandidate && skillCandidate.confidence > 0.5 && onSaveCandidate && (
          <button
            className="skill-save-btn candidate"
            onClick={onSaveCandidate}
            title={`Авто-навык: ${skillCandidate.suggested_name} (confidence: ${Math.round(skillCandidate.confidence * 100)}%)`}
            style={{
              marginLeft: "auto",
              display: "flex",
              alignItems: "center",
              gap: "4px",
              padding: "2px 8px",
              fontSize: "0.6rem",
              background: "var(--accent-soft, rgba(99, 102, 241, 0.12))",
              color: "var(--accent)",
              border: "1px solid var(--accent-border, rgba(99, 102, 241, 0.3))",
              borderRadius: "var(--radius-sm)",
              cursor: "pointer",
              opacity: 1,
            }}
          >
            <Sparkles size={11} />
            Сохранить навык
          </button>
        )}
        {isAssistant && message.content && (!skillCandidate || skillCandidate.confidence <= 0.5) && onSaveSkill && (
          <button
            className="skill-save-btn"
            onClick={() => onSaveSkill(message.content)}
            title="Сохранить как навык"
            style={{
              marginLeft: "auto",
              display: "flex",
              alignItems: "center",
              gap: "4px",
              padding: "2px 8px",
              fontSize: "0.6rem",
              background: "transparent",
              color: "var(--muted)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-sm)",
              cursor: "pointer",
              opacity: 0.6,
            }}
          >
            <Save size={11} />
            Навык
          </button>
        )}
      </div>

      {/* Thinking block */}
      {message.thinking && <ThinkingBlock text={message.thinking} />}

      {/* Tool use */}
      {message.toolUse && (
        <ToolCard
          toolName={message.toolUse.tool_name}
          toolInput={message.toolUse.tool_input}
          result={message.toolResult?.content}
        />
      )}

      {/* Content */}
      {message.content && (
        <div className={`message${isUser ? " system" : isAssistant ? " center" : ""}`}>
          <Markdown text={message.content} />
        </div>
      )}
    </div>
  );
}
