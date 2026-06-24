import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { Send, Paperclip, X } from "lucide-react";

interface MessageInputProps {
  disabled: boolean;
  uploadedFiles: Array<{ name: string; size: number; path: string }>;
  onSend: (message: string) => void;
  onUpload: (files: FileList) => void;
  onRemoveFile: (index: number) => void;
}

export function MessageInput({
  disabled,
  uploadedFiles,
  onSend,
  onUpload,
  onRemoveFile,
}: MessageInputProps) {
  const [value, setValue] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Onboarding: pre-fill chat input after registration
  useEffect(() => {
    const prompt = sessionStorage.getItem("amj-onboarding-prompt");
    if (prompt) {
      setValue(prompt);
      sessionStorage.removeItem("amj-onboarding-prompt");
    }
  }, []);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }, [value, disabled, onSend]);

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  return (
    <div className="input-area" style={{ flexShrink: 0 }}>
      {/* Uploaded files bar */}
      {uploadedFiles.length > 0 && (
        <div
          style={{
            display: "flex",
            gap: "6px",
            flexWrap: "wrap",
            marginBottom: "8px",
          }}
        >
          {uploadedFiles.map((f, i) => (
            <Badge key={i} variant="accent">
              {f.name} ({f.size > 1024 ? `${(f.size / 1024).toFixed(0)}K` : `${f.size}B`})
              <button
                onClick={() => onRemoveFile(i)}
                style={{
                  marginLeft: "4px",
                  background: "none",
                  border: "none",
                  color: "inherit",
                  cursor: "pointer",
                  padding: 0,
                  display: "inline-flex",
                }}
              >
                <X size={10} />
              </button>
            </Badge>
          ))}
        </div>
      )}

      {/* Input row */}
      <div style={{ display: "flex", gap: "8px", alignItems: "flex-end" }}>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          style={{ display: "none" }}
          onChange={(e) => {
            if (e.target.files) onUpload(e.target.files);
            e.target.value = "";
          }}
        />
        <Tooltip content="Прикрепить файлы">
          <Button
            size="icon"
            variant="ghost"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
          >
            <Paperclip size={18} />
          </Button>
        </Tooltip>

        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Опишите задачу..."
          disabled={disabled}
          rows={1}
          style={{ minHeight: "38px", maxHeight: "120px", resize: "none" }}
        />

        <Tooltip content="Отправить (Enter)">
          <Button
            size="icon"
            onClick={handleSend}
            disabled={disabled || !value.trim()}
          >
            <Send size={16} />
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}
