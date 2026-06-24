import { useEffect, useState } from "react";
import { Dialog, DialogBody, DialogClose, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { getSession } from "@/lib/api";
import { Markdown } from "@/components/shared/Markdown";
import type { SessionDetail } from "@/types/models";

interface SessionModalProps {
  open: boolean;
  sessionId: string | null;
  onClose: () => void;
}

export function SessionModal({ open, sessionId, onClose }: SessionModalProps) {
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open && sessionId) {
      setLoading(true);
      getSession(sessionId)
        .then(setSession)
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, [open, sessionId]);

  return (
    <Dialog open={open} onClose={onClose}>
      <DialogHeader>
        <DialogTitle>Сессия {sessionId?.slice(0, 12)}...</DialogTitle>
        <DialogClose onClick={onClose} />
      </DialogHeader>
      <DialogBody>
        {loading ? (
          <div style={{ textAlign: "center", color: "var(--muted)", padding: "20px" }}>Загрузка...</div>
        ) : session ? (
          <div style={{ fontSize: "0.78rem" }}>
            {session.messages.map((m, i) => (
              <div
                key={i}
                style={{
                  marginBottom: "12px",
                  padding: "10px 12px",
                  background: m.role === "user" ? "var(--bg)" : "var(--card)",
                  borderRadius: "var(--radius-sm)",
                  boxShadow: "var(--shadow-card)",
                  borderLeft: `3px solid ${m.role === "user" ? "var(--accent)" : "var(--green)"}`,
                }}
              >
                <div style={{ fontSize: "0.65rem", fontWeight: 500, color: "var(--muted)", marginBottom: "4px" }}>
                  {m.role === "user" ? "Вы" : "Hermes"}
                </div>
                <Markdown text={m.content} compact />
              </div>
            ))}
          </div>
        ) : (
          <div style={{ textAlign: "center", color: "var(--danger)", padding: "20px" }}>Ошибка загрузки</div>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>Закрыть</Button>
      </DialogFooter>
    </Dialog>
  );
}
