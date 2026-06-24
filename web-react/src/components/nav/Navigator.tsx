import { useCallback, useState } from "react";
import { useAppContext } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { SessionsTab } from "./SessionsTab";
import { SkillsTab } from "./SkillsTab";
import { ProjectsTab } from "./ProjectsTab";
import { MemoryGraphTab } from "./MemoryGraphTab";
import { CronTab } from "./CronTab";
import { AdminTab } from "./AdminTab";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

const TABS = [
  { id: "sessions", label: "Сессии" },
  { id: "skills", label: "Навыки" },
  { id: "projects", label: "Проекты" },
  { id: "memory", label: "Память" },
  { id: "cron", label: "Cron" },
];

interface NavigatorProps {
  onSessionClick: (sessionId: string) => void;
}

export function Navigator({ onSessionClick }: NavigatorProps) {
  const { state, dispatch } = useAppContext();
  const { user } = useAuth();
  const { navCollapsed, navWidth, navActiveTab } = state;

  return (
    <div
      className="amj-navigator"
      style={{
        width: navCollapsed ? "28px" : `${navWidth}px`,
        minWidth: navCollapsed ? "28px" : `${navWidth}px`,
        maxWidth: navCollapsed ? "28px" : `${navWidth}px`,
        display: "flex",
        flexDirection: "column",
        background: "var(--surface)",
        borderRight: "1px solid var(--border)",
        overflow: "hidden",
        flexShrink: 0,
        transition: navCollapsed ? "width 0.25s ease, min-width 0.25s ease" : "none",
        boxShadow: "var(--shadow)",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "6px",
          padding: "10px 10px",
          background: "var(--bg)",
          borderBottom: "1px solid var(--border)",
          flexShrink: 0,
          userSelect: "none",
          fontSize: "0.78rem",
          color: "var(--text-bright)",
          fontWeight: 400,
          boxShadow: "var(--shadow)",
        }}
      >
        {!navCollapsed && <span>Навигатор</span>}
        <Tooltip content={navCollapsed ? "Развернуть" : "Свернуть"}>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => dispatch({ type: "SET_NAV_COLLAPSED", collapsed: !navCollapsed })}
            style={{ marginLeft: "auto", padding: "1px 5px", fontSize: "0.6rem" }}
          >
            {navCollapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
          </Button>
        </Tooltip>
      </div>

      {/* Hidden when collapsed */}
      {!navCollapsed && (
        <>
          {/* Tab bar */}
          <div
            style={{
              display: "flex",
              borderBottom: "1px solid var(--border)",
              flexShrink: 0,
              overflow: "auto",
            }}
          >
            {TABS.map((t) => (
              <button
                key={t.id}
                className="nav-tab"
                onClick={() => dispatch({ type: "SET_NAV_TAB", tab: t.id })}
                style={{
                  flex: 1,
                  padding: "6px 4px",
                  fontSize: "0.62rem",
                  background: navActiveTab === t.id ? "var(--accent)" : "transparent",
                  color: navActiveTab === t.id ? "var(--text-on-accent)" : "var(--muted)",
                  border: "none",
                  cursor: "pointer",
                  fontFamily: "inherit",
                  whiteSpace: "nowrap",
                  transition: "all 0.15s",
                }}
              >
                {t.label}
              </button>
            ))}
            {user?.is_admin && (
              <button
                className="nav-tab"
                onClick={() => dispatch({ type: "SET_NAV_TAB", tab: "admin" })}
                style={{
                  flex: 1,
                  padding: "6px 4px",
                  fontSize: "0.62rem",
                  background: navActiveTab === "admin" ? "var(--accent)" : "transparent",
                  color: navActiveTab === "admin" ? "var(--text-on-accent)" : "var(--muted)",
                  border: "none",
                  cursor: "pointer",
                  fontFamily: "inherit",
                  whiteSpace: "nowrap",
                  transition: "all 0.15s",
                }}
              >
                Админ
              </button>
            )}
          </div>

          {/* Tab content */}
          <div style={{ flex: 1, overflow: "hidden" }}>
            {navActiveTab === "sessions" && <SessionsTab onSessionClick={onSessionClick} />}
            {navActiveTab === "skills" && <SkillsTab />}
            {navActiveTab === "projects" && (
              <ProjectsTab
                activeProject={state.activeProjectPath}
                onSelect={(path) => dispatch({ type: "SET_ACTIVE_PROJECT", path })}
              />
            )}
            {navActiveTab === "memory" && <MemoryGraphTab />}
            {navActiveTab === "cron" && <CronTab />}
            {navActiveTab === "admin" && <AdminTab />}
          </div>
        </>
      )}
    </div>
  );
}
