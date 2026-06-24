import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { getSubscriptionStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";

interface AccountModalProps {
  open: boolean;
  onClose: () => void;
}

export function AccountModal({ open, onClose }: AccountModalProps) {
  const { user, logout, apiKey } = useAuth();
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string>("none");
  const [periodEnd, setPeriodEnd] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !user) return;
    setLoading(true);
    getSubscriptionStatus()
      .then((s) => {
        setStatus(s.status);
        setPeriodEnd(s.current_period_end || null);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [open, user]);

  if (!open) return null;

  const maskedKey = apiKey ? apiKey.substring(0, 8) + "..." : "—";

  return (
    <div
      className="modal-overlay"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.6)",
        backdropFilter: "blur(4px)",
      }}
    >
      <div
        className="modal-content"
        style={{
          background: "var(--card)",
          border: "1px solid var(--border)",
          borderRadius: "12px",
          padding: "32px",
          width: "400px",
          maxWidth: "90vw",
          boxShadow: "var(--shadow)",
        }}
      >
        <h2 style={{ margin: "0 0 20px", fontSize: "1.2rem", color: "var(--text)" }}>
          Аккаунт
        </h2>

        <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "0.85rem", color: "var(--text)" }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--muted)" }}>Email</span>
            <span>{user?.email || "—"}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--muted)" }}>API-ключ</span>
            <code style={{ fontSize: "0.75rem", color: "var(--accent)" }}>{maskedKey}</code>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--muted)" }}>Подписка</span>
            <span>{loading ? "..." : status === "active" ? "Активна" : status === "canceled" ? "Отменена" : "Нет"}</span>
          </div>
          {periodEnd && (
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--muted)" }}>Действует до</span>
              <span>{new Date(periodEnd).toLocaleDateString()}</span>
            </div>
          )}
        </div>

        <div style={{ marginTop: "24px", display: "flex", gap: "8px", justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={logout} size="sm">
            Выйти
          </Button>
          <Button variant="ghost" onClick={onClose} size="sm">
            Закрыть
          </Button>
        </div>
      </div>
    </div>
  );
}
