import { useEffect, useState } from "react";
import { Dialog, DialogBody, DialogClose, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { getSelfLearningStatus } from "@/lib/api";
import type { SelfLearningStatus } from "@/types/models";

interface SelfLearningModalProps {
  open: boolean;
  onClose: () => void;
}

export function SelfLearningModal({ open, onClose }: SelfLearningModalProps) {
  const [status, setStatus] = useState<SelfLearningStatus | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open) {
      setLoading(true);
      getSelfLearningStatus()
        .then(setStatus)
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, [open]);

  return (
    <Dialog open={open} onClose={onClose}>
      <DialogHeader>
        <DialogTitle>🧬 Статус самообучения</DialogTitle>
        <DialogClose onClick={onClose} />
      </DialogHeader>
      <DialogBody>
        {loading ? (
          <div style={{ textAlign: "center", color: "var(--muted)", padding: "20px" }}>Загрузка...</div>
        ) : status ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {/* Skills */}
            <div>
              <h4 style={{ fontSize: "0.78rem", marginBottom: "6px", color: "var(--text-bright)" }}>Навыки</h4>
              <div style={{ display: "flex", gap: "4px", height: "20px", borderRadius: "3px", overflow: "hidden" }}>
                {status.skills.local > 0 && (
                  <div
                    style={{
                      width: `${(status.skills.local / status.skills.total) * 100}%`,
                      background: "var(--accent)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "0.6rem",
                      color: "var(--text-on-accent)",
                    }}
                  >
                    {status.skills.local} лок
                  </div>
                )}
                {status.skills.shared > 0 && (
                  <div
                    style={{
                      width: `${(status.skills.shared / status.skills.total) * 100}%`,
                      background: "var(--green)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "0.6rem",
                      color: "var(--text-on-accent)",
                    }}
                  >
                    {status.skills.shared} общ
                  </div>
                )}
                {status.skills.ecc > 0 && (
                  <div
                    style={{
                      width: `${(status.skills.ecc / status.skills.total) * 100}%`,
                      background: "var(--tool-icon)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "0.6rem",
                      color: "var(--text-on-accent)",
                    }}
                  >
                    {status.skills.ecc} ECC
                  </div>
                )}
              </div>
              <div style={{ fontSize: "0.65rem", color: "var(--muted)", marginTop: "4px" }}>
                Всего: {status.skills.total}
              </div>
            </div>

            {/* Memory stats */}
            <div>
              <h4 style={{ fontSize: "0.78rem", marginBottom: "6px", color: "var(--text-bright)" }}>Memory MCP</h4>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "8px",
                  fontSize: "0.68rem",
                }}
              >
                <div style={{ padding: "10px", background: "var(--bg)", borderRadius: "var(--radius-sm)", boxShadow: "var(--shadow-card)" }}>
                  <div style={{ color: "var(--muted)", fontSize: "0.7rem" }}>Фактов</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 600, color: "var(--text-bright)", marginTop: "2px" }}>{status.memory.total}</div>
                </div>
                <div style={{ padding: "10px", background: "var(--bg)", borderRadius: "var(--radius-sm)", boxShadow: "var(--shadow-card)" }}>
                  <div style={{ color: "var(--muted)", fontSize: "0.7rem" }}>Hot cache</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 600, color: "var(--text-bright)", marginTop: "2px" }}>{status.hot_cache.size}</div>
                </div>
                <div style={{ padding: "10px", background: "var(--bg)", borderRadius: "var(--radius-sm)", boxShadow: "var(--shadow-card)" }}>
                  <div style={{ color: "var(--muted)", fontSize: "0.7rem" }}>Project</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 600, color: "var(--text-bright)", marginTop: "2px" }}>{status.memory.project}</div>
                </div>
                <div style={{ padding: "10px", background: "var(--bg)", borderRadius: "var(--radius-sm)", boxShadow: "var(--shadow-card)" }}>
                  <div style={{ color: "var(--muted)", fontSize: "0.7rem" }}>Связей</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 600, color: "var(--text-bright)", marginTop: "2px" }}>{status.memory.relationships}</div>
                </div>
              </div>
            </div>

            {/* Memory budget */}
            <div>
              <h4 style={{ fontSize: "0.78rem", marginBottom: "6px", color: "var(--text-bright)" }}>
                Бюджет памяти: {status.memory_budget.used} / {status.memory_budget.limit} ({status.memory_budget.percent}%)
              </h4>
              <Progress value={status.memory_budget.percent} />
            </div>

            {/* Last session */}
            {status.last_session && (
              <div style={{ fontSize: "0.68rem", color: "var(--muted)" }}>
                Последняя сессия: {status.last_session.started_at}
                <br />
                Проект: {status.last_session.project_path}
              </div>
            )}
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
