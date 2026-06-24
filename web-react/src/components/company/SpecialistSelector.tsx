import { useEffect, useState } from "react";
import { Dialog, DialogBody, DialogClose, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { listCompanySpecialists } from "@/lib/api";
import { useAppContext } from "@/context/AppContext";
import type { SpecialistRole } from "@/types/models";

interface SpecialistSelectorProps {
  open: boolean;
  onClose: () => void;
}

const specialistLabels: Record<string, string> = {
  marketer: "Маркетолог",
  lawyer: "Юрист",
  accountant: "Бухгалтер",
  devops: "DevOps",
};

const specialistIcons: Record<string, string> = {
  marketer: "📈",
  lawyer: "⚖",
  accountant: "💰",
  devops: "⚙",
};

export function SpecialistSelector({ open, onClose }: SpecialistSelectorProps) {
  const { state, dispatch } = useAppContext();
  const [available, setAvailable] = useState<Array<{ name: string; display_name: string; available: boolean }>>([]);
  const [maxForTier, setMaxForTier] = useState(4);
  const [selected, setSelected] = useState<Set<string>>(new Set(state.companySpecialists));
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open) {
      setSelected(new Set(state.companySpecialists));
      setLoading(true);
      listCompanySpecialists()
        .then((res) => {
          setAvailable(res.specialists);
          setMaxForTier(res.max_for_tier);
        })
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, [open, state.companySpecialists]);

  const toggleSpecialist = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else if (next.size < maxForTier) {
        next.add(name);
      }
      return next;
    });
  };

  const handleConfirm = () => {
    dispatch({ type: "SET_COMPANY_SPECIALISTS", specialists: Array.from(selected) as SpecialistRole[] });
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose}>
      <DialogHeader>
        <DialogTitle>Выбор специалистов</DialogTitle>
        <DialogClose onClick={onClose} />
      </DialogHeader>
      <DialogBody>
        {loading ? (
          <div style={{ textAlign: "center", color: "var(--text-muted)", padding: "20px" }}>Загрузка...</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "4px" }}>
              Выберите до {maxForTier} специалистов для параллельного анализа запроса.
              Каждый специалист выполнит свой анализ независимо.
            </div>
            {available.map((spec) => {
              const isChecked = selected.has(spec.name);
              const atLimit = selected.size >= maxForTier && !isChecked;
              return (
                <label
                  key={spec.name}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                    padding: "10px 12px",
                    borderRadius: "var(--radius-sm)",
                    background: isChecked ? "var(--surface-hover)" : "var(--surface)",
                    border: isChecked ? "1px solid var(--accent)" : "1px solid var(--border)",
                    cursor: atLimit || !spec.available ? "not-allowed" : "pointer",
                    opacity: atLimit || !spec.available ? 0.5 : 1,
                    transition: "background 0.15s, border 0.15s",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    disabled={atLimit || !spec.available}
                    onChange={() => toggleSpecialist(spec.name)}
                    style={{ accentColor: "var(--accent)", cursor: "pointer" }}
                  />
                  <span style={{ fontSize: "1rem" }}>{specialistIcons[spec.name] || "👤"}</span>
                  <span style={{ fontSize: "0.8rem", fontWeight: 500, color: "var(--text-bright)" }}>
                    {specialistLabels[spec.name] || spec.display_name}
                  </span>
                  {!spec.available && (
                    <span style={{ fontSize: "0.65rem", color: "var(--text-muted)", marginLeft: "auto" }}>
                      Недоступен
                    </span>
                  )}
                </label>
              );
            })}
            {selected.size > 0 && (
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", textAlign: "center" }}>
                Выбрано: {selected.size}/{maxForTier}
              </div>
            )}
          </div>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>Отмена</Button>
        <Button onClick={handleConfirm} disabled={selected.size === 0 || loading}>
          Применить
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
