import { useState, useEffect, useCallback, useMemo } from "react";
import { Dialog, DialogBody, DialogClose, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, type SelectOption } from "@/components/ui/select";
import { Tooltip } from "@/components/ui/tooltip";
import { useThemeContext } from "@/context/ThemeContext";
import { useAppContext } from "@/context/AppContext";
import { getModelCurrent, getModelList, postModelSwitch } from "@/lib/api";

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsModal({ open, onClose }: SettingsModalProps) {
  const { theme, toggleTheme } = useThemeContext();
  const { state, dispatch } = useAppContext();
  const [apiModels, setApiModels] = useState<SelectOption[]>([]);

  const maxSides = 2;
  const sideLocked = false;
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(() => {
    if (!open) return;
    setLoading(true);
    Promise.all([
      getModelCurrent().catch(() => null),
      getModelList().catch(() => null),
    ])
      .then(([current, list]) => {
        // Только центр синхронизируется с бэкендом. Левая/правая — локальное состояние.
        if (current) {
          dispatch({ type: "SET_MODEL", panel: "center", modelId: current.model });
        }
        if (list?.models?.length) {
          setApiModels(list.models.map((m) => ({ value: m.id, label: m.name })));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [open, dispatch]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Merge API models with current selection to ensure the selected model is always an option
  const models = useMemo(() => {
    const seen = new Set(apiModels.map((m) => m.value));
    const result = [...apiModels];
    for (const key of ["center", "left", "right"] as const) {
      const v = state.model[key];
      if (v && !seen.has(v)) {
        seen.add(v);
        result.push({ value: v, label: v });
      }
    }
    return result;
  }, [apiModels, state.model]);

  const handleModelChange = async (panel: "center" | "left" | "right", modelId: string) => {
    if (!modelId) return;
    dispatch({ type: "SET_MODEL", panel, modelId });
    // Только центральная модель переключается глобально на бэкенде.
    // Левая/правая — локальное состояние (side-модели настраиваются отдельно).
    if (panel === "center") {
      try {
        await postModelSwitch({ model: modelId });
      } catch (_err) {
        // rollback on failure
        dispatch({ type: "SET_MODEL", panel, modelId: state.model.center });
      }
    }
  };

  return (
    <Dialog open={open} onClose={onClose}>
      <DialogHeader>
        <DialogTitle>Настройки</DialogTitle>
        <DialogClose onClick={onClose} />
      </DialogHeader>
      <DialogBody>
        <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
          {/* Theme */}
          <div>
            <Label>Тема</Label>
            <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
              <Tooltip content="Тёмная тема">
                <Button
                  variant={theme === "dark" ? "default" : "outline"}
                  onClick={() => theme !== "dark" && toggleTheme()}
                  size="sm"
                >
                  Тёмная
                </Button>
              </Tooltip>
              <Tooltip content="Светлая тема">
                <Button
                  variant={theme === "light" ? "default" : "outline"}
                  onClick={() => theme !== "light" && toggleTheme()}
                  size="sm"
                >
                  Светлая
                </Button>
              </Tooltip>
            </div>
          </div>

          {/* Comfort mode */}
          <div>
            <Label>Режим Comfort</Label>
            <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
              <Tooltip content="Снижение контраста и тёплый фильтр для длительной работы">
                <Button
                  variant={state.comfortMode ? "default" : "outline"}
                  onClick={() => dispatch({ type: "TOGGLE_COMFORT", enabled: !state.comfortMode })}
                  size="sm"
                >
                  {state.comfortMode ? "Включён" : "Выключен"}
                </Button>
              </Tooltip>
            </div>
          </div>

          {/* Center model */}
          <div>
            <Label>Центральная модель (Judge)</Label>
            {loading ? (
              <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Загрузка...</span>
            ) : (
              <Select
                options={models}
                value={state.model.center}
                onChange={(e) => handleModelChange("center", e.target.value)}
              />
            )}
          </div>

          {/* Left model */}
          <div>
            <Label>
              Левая модель (Эксперт A)
            </Label>
            {loading ? (
              <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Загрузка...</span>
            ) : (
              <Select
                options={models}
                value={state.model.left}
                onChange={(e) => handleModelChange("left", e.target.value)}
              />
            )}
          </div>

          {/* Right model */}
          <div>
            <Label>
              Правая модель (Эксперт B)
            </Label>
            {loading ? (
              <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Загрузка...</span>
            ) : (
              <Select
                options={models}
                value={state.model.right}
                onChange={(e) => handleModelChange("right", e.target.value)}
              />
            )}
          </div>
        </div>
      </DialogBody>
      <DialogFooter>
        <Tooltip content="Закрыть настройки">
          <Button variant="ghost" onClick={onClose}>Закрыть</Button>
        </Tooltip>
      </DialogFooter>
    </Dialog>
  );
}
