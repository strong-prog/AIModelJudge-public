import { useEffect, useRef } from "react";
import type { ChatMessage as ChatMessageType, SkillCandidate } from "@/types/models";
import { ChatMessage } from "./ChatMessage";
import { LoadingDots } from "@/components/shared/LoadingDots";

interface ChatContainerProps {
  messages: ChatMessageType[];
  streaming: boolean;
  onSaveSkill?: (content: string) => void;
  skillCandidate?: SkillCandidate | null;
  onSaveCandidate?: () => void;
}

export function ChatContainer({ messages, streaming, onSaveSkill, skillCandidate, onSaveCandidate }: ChatContainerProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);

  useEffect(() => {
    if (shouldAutoScroll.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const onScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    shouldAutoScroll.current = scrollHeight - scrollTop - clientHeight < 50;
  };

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      style={{
        flex: 1,
        overflow: "auto",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {messages.length === 0 && !streaming && (
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--muted)",
            fontSize: "0.8rem",
            textAlign: "center",
            padding: "40px",
          }}
        >
          <div>
            <div style={{ fontSize: "1.5rem", marginBottom: "12px", fontWeight: 600, color: "var(--text-heading)", letterSpacing: "-0.02em" }}>Hermes Agent</div>
            <div style={{ color: "var(--muted)", maxWidth: "320px", lineHeight: "var(--line-height)" }}>Опишите задачу, и Central Judge разберёт её по фазам</div>
          </div>
        </div>
      )}

      {messages.map((msg) => (
        <ChatMessage key={msg.id} message={msg} onSaveSkill={onSaveSkill} skillCandidate={skillCandidate} onSaveCandidate={onSaveCandidate} />
      ))}

      {streaming && (
        <div style={{ padding: "10px 18px" }}>
          <LoadingDots />
        </div>
      )}
    </div>
  );
}
