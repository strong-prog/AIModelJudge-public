import { useEffect, useState, useCallback } from "react";
import {
  getCronList,
  postCronTrigger,
  postCronToggle,
  postCronCreate,
  deleteCronJob,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { timeAgo } from "@/lib/utils";
import type { CronJob } from "@/types/models";
import { Play, Pause, Trash2, Plus, X } from "lucide-react";

export function CronTab() {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newPrompt, setNewPrompt] = useState("");
  const [newSchedule, setNewSchedule] = useState("");

  const refresh = useCallback(() => {
    getCronList()
      .then((r) => setJobs(r.jobs))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleToggle = async (jobId: string, action: "pause" | "resume") => {
    try {
      await postCronToggle({ job_id: jobId, action });
      refresh();
    } catch {}
  };

  const handleTrigger = async (jobId: string) => {
    try {
      await postCronTrigger({ job_id: jobId });
      refresh();
    } catch {}
  };

  const handleDelete = async (jobId: string) => {
    if (!confirm("Удалить задачу?")) return;
    try {
      await deleteCronJob(jobId);
      refresh();
    } catch {}
  };

  const handleCreate = async () => {
    if (!newName || !newPrompt || !newSchedule) return;
    try {
      await postCronCreate({ name: newName, prompt: newPrompt, schedule: newSchedule });
      setShowCreate(false);
      setNewName("");
      setNewPrompt("");
      setNewSchedule("");
      refresh();
    } catch {}
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ padding: "6px 8px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: "0.7rem", color: "var(--muted)" }}>{jobs.length} задач</span>
        <Button size="sm" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? <X size={14} /> : <Plus size={14} />}
        </Button>
      </div>

      {showCreate && (
        <div style={{ padding: "8px", borderBottom: "1px solid var(--border)" }}>
          <Input
            placeholder="Название"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            style={{ marginBottom: "4px", fontSize: "0.7rem" }}
          />
          <Textarea
            placeholder="Промпт"
            value={newPrompt}
            onChange={(e) => setNewPrompt(e.target.value)}
            rows={2}
            style={{ marginBottom: "4px", fontSize: "0.7rem", minHeight: "40px" }}
          />
          <Input
            placeholder="Расписание (напр. every 1h)"
            value={newSchedule}
            onChange={(e) => setNewSchedule(e.target.value)}
            style={{ marginBottom: "6px", fontSize: "0.7rem" }}
          />
          <Button size="sm" onClick={handleCreate}>
            Создать
          </Button>
        </div>
      )}

      <ScrollArea style={{ flex: 1 }}>
        {jobs.map((j) => (
          <div
            key={j.id}
            style={{
              padding: "8px 10px",
              borderBottom: "1px solid var(--border)",
              borderLeft: `3px solid ${
                j.state === "scheduled" ? "var(--green)" : j.state === "paused" ? "var(--tool-icon)" : "var(--accent)"
              }`,
            }}
          >
            <div style={{ fontSize: "0.7rem", color: "var(--text-bright)" }}>{j.name}</div>
            <div style={{ display: "flex", gap: "4px", margin: "4px 0" }}>
              <Badge
                variant={j.state === "scheduled" ? "green" : j.state === "paused" ? "default" : "accent"}
              >
                {j.state}
              </Badge>
              <span style={{ fontSize: "0.6rem", color: "var(--muted)" }}>{j.schedule_display}</span>
            </div>
            {j.last_run_at && (
              <div style={{ fontSize: "0.55rem", color: "var(--muted)" }}>
                Последний запуск: {timeAgo(j.last_run_at)}
              </div>
            )}
            <div style={{ display: "flex", gap: "4px", marginTop: "6px" }}>
              <Button size="sm" variant="ghost" onClick={() => handleTrigger(j.id)}>
                <Play size={12} />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => handleToggle(j.id, j.state === "paused" ? "resume" : "pause")}
              >
                <Pause size={12} />
              </Button>
              <Button size="sm" variant="ghost" onClick={() => handleDelete(j.id)}>
                <Trash2 size={12} />
              </Button>
            </div>
          </div>
        ))}
      </ScrollArea>
    </div>
  );
}
