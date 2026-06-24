import { useState, useCallback, useEffect } from "react";
import { Dialog, DialogBody, DialogClose, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Tooltip } from "@/components/ui/tooltip";
import { postSkillsCreate, postSkillsCreateFromSession } from "@/lib/api";
import type { SkillsCreateResponse } from "@/types/api";
import type { SkillCandidate } from "@/types/models";

interface SaveSkillModalProps {
  open: boolean;
  onClose: () => void;
  defaultContent?: string;
  candidate?: SkillCandidate | null;
  onSuccess?: (res: SkillsCreateResponse) => void;
  onCreated?: () => void;
}

export function SaveSkillModal({ open, onClose, defaultContent, candidate, onSuccess, onCreated }: SaveSkillModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      if (candidate) {
        setName(candidate.suggested_name);
        setDescription(candidate.description);
        setContent(candidate.content);
      } else {
        setName("");
        setDescription("");
        setContent(defaultContent || "");
      }
      setError(null);
    }
  }, [open, candidate, defaultContent]);

  const handleSave = useCallback(async () => {
    if (!name.trim() || !description.trim()) {
      setError("Имя и описание обязательны");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      let res: SkillsCreateResponse;
      if (candidate) {
        res = await postSkillsCreateFromSession({
          session_id: candidate.session_id,
          name: name.trim(),
          description: description.trim(),
          content: content.slice(0, 100000),
        });
      } else {
        res = await postSkillsCreate({
          name: name.trim(),
          description: description.trim(),
          content: content.slice(0, 100000),
        });
      }
      onSuccess?.(res);
      onCreated?.();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  }, [name, description, content, candidate, onClose, onSuccess, onCreated]);

  return (
    <Dialog open={open} onClose={onClose}>
      <DialogHeader>
        <DialogTitle>Сохранить как навык</DialogTitle>
        <DialogClose onClick={onClose} />
      </DialogHeader>
      <DialogBody>
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          <div>
            <Label>Имя навыка (kebab-case)</Label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my-skill"
              spellCheck={false}
              style={{
                width: "100%",
                boxSizing: "border-box",
                marginTop: "4px",
                padding: "8px 10px",
                fontSize: "0.8rem",
                fontFamily: "var(--mono, monospace)",
                background: "var(--input-bg)",
                color: "var(--text-bright)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
              }}
            />
          </div>
          <div>
            <Label>Описание</Label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Краткое описание навыка"
              maxLength={1024}
              style={{
                width: "100%",
                boxSizing: "border-box",
                marginTop: "4px",
                padding: "8px 10px",
                fontSize: "0.8rem",
                background: "var(--input-bg)",
                color: "var(--text-bright)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
              }}
            />
          </div>
          <div>
            <Label>Содержимое (Markdown)</Label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={10}
              style={{
                width: "100%",
                boxSizing: "border-box",
                marginTop: "4px",
                padding: "8px 10px",
                fontSize: "0.75rem",
                fontFamily: "var(--mono, monospace)",
                background: "var(--input-bg)",
                color: "var(--text-bright)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                resize: "vertical",
              }}
            />
          </div>
          {error && (
            <div style={{ fontSize: "0.7rem", color: "var(--danger)" }}>{error}</div>
          )}
        </div>
      </DialogBody>
      <DialogFooter>
        <Tooltip content="Отмена">
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
        </Tooltip>
        <Tooltip content="Сохранить навык">
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Сохранение..." : "Сохранить"}
          </Button>
        </Tooltip>
      </DialogFooter>
    </Dialog>
  );
}
