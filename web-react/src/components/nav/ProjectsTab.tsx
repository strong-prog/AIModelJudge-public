import { useEffect, useState, useCallback } from "react";
import { getProjectsList, getProjectsContext } from "@/lib/api";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatBytes } from "@/lib/utils";
import type { Project } from "@/types/models";

interface ProjectsTabProps {
  activeProject: string;
  onSelect: (path: string) => void;
}

export function ProjectsTab({ activeProject, onSelect }: ProjectsTabProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [contexts, setContexts] = useState<Record<string, { files: number; dirs: number; size: number }>>({});

  useEffect(() => {
    getProjectsList()
      .then((r) => {
        setProjects(r.projects);
        r.projects.forEach((p) => {
          getProjectsContext(p.path)
            .then((c) => setContexts((prev) => ({ ...prev, [p.path]: c })))
            .catch(() => {});
        });
      })
      .catch(() => {});
  }, []);

  return (
    <ScrollArea style={{ height: "100%" }}>
      <div style={{ padding: "4px 0" }}>
        {projects.map((p) => {
          const ctx = contexts[p.path];
          const isActive = p.path === activeProject;
          return (
            <div
              key={p.path}
              onClick={() => onSelect(p.path)}
              style={{
                padding: "8px 10px",
                cursor: "pointer",
                borderBottom: "1px solid var(--border)",
                background: isActive ? "var(--bg)" : "transparent",
                borderLeft: isActive ? "2px solid var(--accent)" : "2px solid transparent",
                transition: "all 0.1s",
              }}
            >
              <div style={{ fontSize: "0.7rem", color: "var(--text-bright)" }}>{p.name}</div>
              <div style={{ fontSize: "0.55rem", color: "var(--muted)", marginTop: "2px" }}>
                {p.path}
              </div>
              {ctx && (
                <div style={{ fontSize: "0.55rem", color: "var(--muted)", marginTop: "2px" }}>
                  {ctx.files} files · {ctx.dirs} dirs · {formatBytes(ctx.size)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}
