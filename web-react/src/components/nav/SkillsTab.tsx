import { useEffect, useState, useMemo, useCallback } from "react";
import { getSkillsList, getSkillsContent, postSkillsRate } from "@/lib/api";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Markdown } from "@/components/shared/Markdown";
import { SkillGraphTab } from "./SkillGraphTab";
import { ThumbsUp, ThumbsDown, Flame, List, GitGraph } from "lucide-react";
import type { Skill, SkillNode } from "@/types/models";

type ViewMode = "list" | "graph";

export function SkillsTab() {
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [hotSkills, setHotSkills] = useState<Skill[]>([]);
  const [activeSkill, setActiveSkill] = useState<Skill | null>(null);
  const [content, setContent] = useState<string>("");
  const [skillMetrics, setSkillMetrics] = useState<Record<string, { call_count: number; upvotes: number; downvotes: number; hot_score?: number; is_hot?: boolean }>>({});

  const fetchSkills = useCallback(() => {
    getSkillsList()
      .then((r) => {
        setSkills(r.skills);
        if (r.hot_skills) setHotSkills(r.hot_skills);
        const meta: Record<string, { call_count: number; upvotes: number; downvotes: number; hot_score?: number; is_hot?: boolean }> = {};
        r.skills.forEach((s) => {
          meta[s.path] = { call_count: s.call_count || 0, upvotes: s.upvotes || 0, downvotes: s.downvotes || 0, hot_score: s.hot_score, is_hot: s.is_hot };
        });
        setSkillMetrics(meta);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  const sortedSkills = useMemo(() => {
    return [...skills].sort((a, b) => {
      const aScore = skillMetrics[a.path]?.hot_score ?? 0;
      const bScore = skillMetrics[b.path]?.hot_score ?? 0;
      if (bScore !== aScore) return bScore - aScore;
      return a.name.localeCompare(b.name);
    });
  }, [skills, skillMetrics]);

  const handleRate = useCallback(async (path: string, rating: "up" | "down") => {
    try {
      const res = await postSkillsRate({ path, rating });
      setSkillMetrics((prev) => ({
        ...prev,
        [path]: { call_count: res.call_count, upvotes: res.upvotes, downvotes: res.downvotes },
      }));
    } catch {}
  }, []);

  const handleGraphNodeClick = useCallback((node: SkillNode) => {
    const skill = skills.find((s) => s.path === node.path || s.path === node.id);
    if (skill) {
      setActiveSkill(skill);
      getSkillsContent(skill.path)
        .then((r) => setContent(r.content))
        .catch(() => setContent(""));
      setViewMode("list");
    }
  }, [skills]);

  const typeColors: Record<string, "accent" | "green" | "default"> = {
    local: "accent",
    shared: "green",
    ecc: "default",
  };

  const typeLabels: Record<string, string> = {
    local: "Лок",
    shared: "Общ",
    ecc: "ECC",
  };

  const renderSkillItem = (s: Skill, m: { call_count: number; upvotes: number; downvotes: number; hot_score?: number; is_hot?: boolean }) => {
    const hs = m.hot_score ?? 0;
    return (
      <div
        key={s.path}
        className="skill-item"
        onClick={() => {
          setActiveSkill(s);
          getSkillsContent(s.path)
            .then((r) => setContent(r.content))
            .catch(() => setContent(""));
        }}
        style={{
          padding: "8px 10px",
          cursor: "pointer",
          borderBottom: "1px solid var(--border)",
          background: activeSkill?.path === s.path ? "var(--bg)" : "transparent",
          transition: "background 0.1s",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
            {m.is_hot && <Flame size={10} style={{ color: "var(--danger)" }} />}
            <span style={{ fontSize: "0.7rem", color: "var(--text-bright)" }}>{s.name}</span>
          </span>
          <div className="skill-rating" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => handleRate(s.path, "up")}
              title="👍 Полезный"
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "1px 3px",
                color: "var(--muted)",
                fontSize: "0.55rem",
                display: "flex",
                alignItems: "center",
                gap: "1px",
              }}
            >
              <ThumbsUp size={10} />
              <span>{m.upvotes || 0}</span>
            </button>
            <button
              onClick={() => handleRate(s.path, "down")}
              title="👎 Бесполезный"
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "1px 3px",
                color: "var(--muted)",
                fontSize: "0.55rem",
                display: "flex",
                alignItems: "center",
                gap: "1px",
              }}
            >
              <ThumbsDown size={10} />
              <span>{m.downvotes || 0}</span>
            </button>
          </div>
        </div>
        <div style={{ display: "flex", gap: "4px", marginTop: "2px", alignItems: "center" }}>
          <Badge variant={typeColors[s.type]}>{typeLabels[s.type]}</Badge>
          {s.description && (
            <span style={{ fontSize: "0.6rem", color: "var(--muted)" }}>
              {s.description.slice(0, 40)}
            </span>
          )}
          {m.call_count > 0 && (
            <span style={{ fontSize: "0.55rem", color: "var(--muted)", marginLeft: "auto" }}>
              {m.call_count}×
            </span>
          )}
          {hs > 0 && (
            <span style={{ fontSize: "0.5rem", color: "var(--accent)", fontWeight: 500 }}>
              {hs.toFixed(2)}
            </span>
          )}
        </div>
      </div>
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Tab selector */}
      <div
        style={{
          display: "flex",
          borderBottom: "1px solid var(--border)",
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => setViewMode("list")}
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "4px",
            padding: "6px 0",
            fontSize: "0.6rem",
            fontWeight: viewMode === "list" ? 600 : 400,
            color: viewMode === "list" ? "var(--text-bright)" : "var(--muted)",
            background: viewMode === "list" ? "var(--bg)" : "transparent",
            border: "none",
            borderBottom: viewMode === "list" ? "2px solid var(--accent)" : "2px solid transparent",
            cursor: "pointer",
          }}
        >
          <List size={11} />
          Список
        </button>
        <button
          onClick={() => setViewMode("graph")}
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "4px",
            padding: "6px 0",
            fontSize: "0.6rem",
            fontWeight: viewMode === "graph" ? 600 : 400,
            color: viewMode === "graph" ? "var(--text-bright)" : "var(--muted)",
            background: viewMode === "graph" ? "var(--bg)" : "transparent",
            border: "none",
            borderBottom: viewMode === "graph" ? "2px solid var(--accent)" : "2px solid transparent",
            cursor: "pointer",
          }}
        >
          <GitGraph size={11} />
          Граф
        </button>
      </div>

      {/* Content */}
      {viewMode === "graph" ? (
        <SkillGraphTab onNodeClick={handleGraphNodeClick} />
      ) : (
        <>
          <ScrollArea style={{ flex: 1 }}>
            {hotSkills.length > 0 && (
              <div style={{ padding: "4px 10px" }}>
                <span style={{ fontSize: "0.6rem", fontWeight: 600, color: "var(--danger)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Горячие навыки
                </span>
              </div>
            )}
            {sortedSkills.map((s) => {
              const m = skillMetrics[s.path] || { call_count: 0, upvotes: 0, downvotes: 0, hot_score: 0, is_hot: false };
              return renderSkillItem(s, m);
            })}
          </ScrollArea>
          {activeSkill && content && (
            <div
              style={{
                borderTop: "1px solid var(--border)",
                padding: "10px",
                maxHeight: "40%",
                overflow: "auto",
              }}
            >
              <div style={{ fontSize: "0.75rem", fontWeight: 500, marginBottom: "4px", color: "var(--text-bright)" }}>
                {activeSkill.name}
              </div>
              <div style={{ fontSize: "0.6rem" }}>
                <Markdown text={content} compact />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
