import { type ReactNode } from "react";

interface ChatScreenProps {
  header: ReactNode;
  children: ReactNode;
  input: ReactNode;
}

export function ChatScreen({ header, children, input }: ChatScreenProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        minWidth: 0,
        height: "100dvh",
        background: "var(--bg)",
      }}
    >
      {header}
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {children}
      </div>
      {input}
    </div>
  );
}
