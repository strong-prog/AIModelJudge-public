import { useEffect, useState, useCallback } from "react";
import {
  getKanbanTasks,
  postKanbanCreate,
  patchKanbanTask,
  deleteKanbanTask,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useAppContext } from "@/context/AppContext";
import { Trash2, Plus, ArrowRight, ArrowLeft } from "lucide-react";
import type { KanbanTask } from "@/types/models";

const COLUMNS = [
  { id: "subagents", label: "Агенты", color: "var(--accent)" },
  { id: "tasks", label: "Задачи", color: "var(--tool-icon)" },
  { id: "edits", label: "Правки", color: "var(--green)" },
] as const;

interface KanbanBoardProps {
  visible: boolean;
}

export function KanbanBoard({ visible }: KanbanBoardProps) {
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [newTitle, setNewTitle] = useState("");
  const { state } = useAppContext();

  const refresh = useCallback(() => {
    getKanbanTasks()
      .then((r) => setTasks(r.tasks))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, state.kanbanUpdateVersion]);

  const handleCreate = async () => {
    if (!newTitle.trim()) return;
    try {
      await postKanbanCreate({ title: newTitle, column: "tasks" });
      setNewTitle("");
      refresh();
    } catch {}
  };

  const handleMove = async (taskId: string, fromCol: string, toCol: string) => {
    try {
      await patchKanbanTask(taskId, { column: toCol });
      setTasks((prev) =>
        prev.map((t) => (t.id === taskId ? { ...t, column: toCol as KanbanTask["column"] } : t))
      );
    } catch {}
  };

  const handleDelete = async (taskId: string) => {
    try {
      await deleteKanbanTask(taskId);
      setTasks((prev) => prev.filter((t) => t.id !== taskId));
    } catch {}
  };

  if (!visible) return null;

  const tasksByColumn = (col: string) => tasks.filter((t) => t.column === col);

  return (
    <div className="kanban-board">
      {/* Header */}
      <div className="kanban-header">
        <span className="kanban-title">Kanban</span>
        <Input
          placeholder="Новая задача..."
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          style={{ flex: 1, maxWidth: "300px", fontSize: "0.7rem", height: "28px" }}
        />
        <Tooltip content="Добавить задачу">
          <Button size="sm" onClick={handleCreate}>
            <Plus size={12} />
          </Button>
        </Tooltip>
      </div>

      {/* Columns */}
      <div className="kanban-columns">
        {COLUMNS.map((col) => (
          <div
            key={col.id}
            className="kanban-column"
          >
            <div
              className="kanban-column-header"
              style={{ color: col.color }}
            >
              <span>{col.label}</span>
              <Badge>{tasksByColumn(col.id).length}</Badge>
            </div>
            <ScrollArea style={{ flex: 1, padding: "4px" }}>
              {tasksByColumn(col.id).map((t) => (
                <div key={t.id} className="kanban-card">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</span>
                    <div style={{ display: "flex", gap: "2px", flexShrink: 0, marginLeft: "4px" }}>
                      <Tooltip content="Удалить задачу">
                        <Button size="sm" variant="ghost" onClick={() => handleDelete(t.id)}>
                          <Trash2 size={10} />
                        </Button>
                      </Tooltip>
                    </div>
                  </div>
                  {/* Move buttons */}
                  <div style={{ display: "flex", gap: "2px", marginTop: "4px" }}>
                    {COLUMNS.filter((c) => c.id !== col.id).map((targetCol) => (
                      <Tooltip key={targetCol.id} content={`Переместить в «${targetCol.label}»`}>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleMove(t.id, col.id, targetCol.id)}
                          style={{ fontSize: "0.55rem", padding: "2px 3px" }}
                        >
                          {COLUMNS.indexOf(targetCol) < COLUMNS.indexOf(col) ? (
                            <ArrowLeft size={10} />
                          ) : (
                            <ArrowRight size={10} />
                          )}
                        </Button>
                      </Tooltip>
                    ))}
                  </div>
                </div>
              ))}
            </ScrollArea>
          </div>
        ))}
      </div>
    </div>
  );
}
