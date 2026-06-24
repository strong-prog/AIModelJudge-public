import { useState, useEffect } from "react";
import { PhaseIndicator } from "./PhaseIndicator";
import { useAppContext } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useThemeContext } from "@/context/ThemeContext";
import { Tooltip } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Brain, Dna, BarChart3, Sun, Moon, Eye, EyeOff, PanelLeft, PanelRight, X, Building2, Users, Monitor, MonitorOff } from "lucide-react";
import { activateProfile } from "@/lib/api";

interface ChatHeaderProps {
  onMemoryGraphClick?: () => void;
  onSelfLearningClick?: () => void;
  onAnalyticsClick?: () => void;
  onTierClick?: () => void;
  onSpecialistClick?: () => void;
}

export function ChatHeader({
  onMemoryGraphClick,
  onSelfLearningClick,
  onAnalyticsClick,
  onTierClick,
  onSpecialistClick,
}: ChatHeaderProps) {
  const { state, dispatch } = useAppContext();
  const { theme, toggleTheme } = useThemeContext();
  const { user } = useAuth();
  const { model, subagentCount, streaming, phase: currentPhase, activeProfile, availableProfiles, panelLeftState, panelRightState, companyMode, companySpecialists, devMode, agentConnected } = state;

  const [showOnboarding, setShowOnboarding] = useState(false);

  useEffect(() => {
    const dismissed = localStorage.getItem("amj-onboarding-profile");
    if (dismissed) return;
    if (availableProfiles.length === 1) {
      const p = availableProfiles[0];
      if ((p.session_count ?? 0) >= 5) {
        setShowOnboarding(true);
      }
    }
  }, [availableProfiles]);

  const dismissOnboarding = () => {
    localStorage.setItem("amj-onboarding-profile", "1");
    setShowOnboarding(false);
  };

  const handleProfileSwitch = async (profileId: string) => {
    if (profileId === activeProfile) return;
    try {
      await activateProfile(profileId);
      localStorage.setItem("amj-profile", profileId);
      dispatch({ type: "SET_PROFILE", profile: profileId });
    } catch (e) {
      // ignore
    }
  };

  return (
    <>
      {showOnboarding && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "4px 8px",
            background: "var(--accent)",
            color: "#fff",
            fontSize: "0.75rem",
            gap: "8px",
            flexShrink: 0,
          }}
        >
          <span>
            Вы провели 5+ сессий с профилем по умолчанию.{" "}
            <span
              onClick={() => dispatch({ type: "SET_NAV_TAB", tab: "sessions" })}
              style={{ fontWeight: 700, cursor: "pointer", textDecoration: "underline" }}
            >
              Создайте свой профиль
            </span>
            {" "}для персонализации AI-ассистента.
          </span>
          <button
            onClick={dismissOnboarding}
            style={{ background: "none", border: "none", color: "#fff", cursor: "pointer", padding: 0, display: "flex" }}
          >
            <X size={14} />
          </button>
        </div>
      )}
      <div
        className="amj-chat-header"
        style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        padding: "8px 12px",
        background: "var(--surface)",
        borderBottom: "1px solid var(--border)",
        flexShrink: 0,
        userSelect: "none",
        justifyContent: "space-between",
      }}
    >
      {/* Left side: profile selector + model name + phase + subagent count */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0 }}>
        {availableProfiles.length > 1 && (
          <select
            className="amj-profile-select"
            value={activeProfile}
            onChange={(e) => handleProfileSwitch(e.target.value)}
            style={{
              fontSize: "0.7rem",
              background: "var(--surface-hover)",
              color: "var(--text-muted)",
              border: "1px solid var(--border)",
              borderRadius: "4px",
              padding: "2px 4px",
              cursor: "pointer",
              flexShrink: 0,
              maxWidth: "120px",
            }}
          >
            {availableProfiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        <span
          style={{
            fontSize: "0.78rem",
            color: "var(--text-bright)",
            fontWeight: 400,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {model.center || "Hermes Agent"}
        </span>

        <span style={{ cursor: "pointer" }} onClick={onTierClick}>
          <Badge variant="default">Account</Badge>
        </span>

        {streaming && <PhaseIndicator currentPhase={state.phase} />}

        {subagentCount > 0 && (
          <Badge variant="accent" title={`${subagentCount} active subagents`}>
            ⚙ {subagentCount}
          </Badge>
        )}
      </div>

      {/* Right side: action buttons */}
      <div style={{ display: "flex", alignItems: "center", gap: "2px", flexShrink: 0 }}>
        {panelLeftState === "closed" && (
          <Tooltip content="Открыть левую панель">
            <Button
              size="icon"
              variant="ghost"
              onClick={() => dispatch({ type: "SET_PANEL_LEFT", state: "open" })}
            >
              <PanelLeft size={14} />
            </Button>
          </Tooltip>
        )}
        {panelRightState === "closed" && (
          <Tooltip content="Открыть правую панель">
            <Button
              size="icon"
              variant="ghost"
              onClick={() => dispatch({ type: "SET_PANEL_RIGHT", state: "open" })}
            >
              <PanelRight size={14} />
            </Button>
          </Tooltip>
        )}

        <Tooltip content={theme === "dark" ? "Светлая тема" : "Тёмная тема"}>
          <Button size="icon" variant="ghost" onClick={toggleTheme}>
            {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
          </Button>
        </Tooltip>

        <Tooltip content={state.comfortMode ? "Выключить Comfort" : "Режим Comfort"}>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => dispatch({ type: "TOGGLE_COMFORT", enabled: !state.comfortMode })}
          >
            {state.comfortMode ? <EyeOff size={14} /> : <Eye size={14} />}
          </Button>
        </Tooltip>

        <Tooltip content={companyMode ? "Режим Expert" : "Режим Company"}>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => {
              const enabled = !companyMode;
              dispatch({ type: "TOGGLE_COMPANY_MODE", enabled });
              if (enabled && companySpecialists.length === 0) {
                dispatch({ type: "SET_COMPANY_SPECIALISTS", specialists: ["marketer", "lawyer"] });
              }
            }}
          >
            {companyMode ? <Users size={14} /> : <Building2 size={14} />}
          </Button>
        </Tooltip>
        {companyMode && onSpecialistClick && (
          <Tooltip content="Настроить специалистов">
            <span
              onClick={onSpecialistClick}
              style={{
                cursor: "pointer",
                fontSize: "0.65rem",
                color: "var(--accent)",
                background: "var(--surface-hover)",
                borderRadius: "4px",
                padding: "1px 5px",
                fontWeight: 600,
              }}
            >
              {companySpecialists.length}
            </span>
          </Tooltip>
        )}

        {user && (
          <Tooltip content={devMode ? (agentConnected ? "Dev Mode (агент подключен)" : "Dev Mode (агент не подключен)") : "Dev Mode"}>
            <Button
              size="icon"
              variant="ghost"
              onClick={() => {
                const enabled = !devMode;
                dispatch({ type: "TOGGLE_DEV_MODE", enabled });
                if (enabled && !agentConnected) {
                  import("@/lib/api").then((api) => {
                    api.getAgentStatus().then((status) => {
                      dispatch({
                        type: "SET_AGENT_STATUS",
                        connected: status.connected,
                        version: status.version,
                        projectRoot: status.project_root,
                      });
                    }).catch(() => {});
                  });
                }
              }}
              style={devMode && agentConnected ? { color: "var(--accent)" } : undefined}
            >
              {devMode ? <Monitor size={14} /> : <MonitorOff size={14} />}
            </Button>
          </Tooltip>
        )}

        <span style={{ width: "1px", height: "16px", background: "var(--border)", margin: "0 2px" }} />

        <Tooltip content="Граф памяти">
          <Button size="icon" variant="ghost" onClick={onMemoryGraphClick}>
            <Brain size={14} />
          </Button>
        </Tooltip>

        <Tooltip content="Статус самообучения">
          <Button size="icon" variant="ghost" onClick={onSelfLearningClick}>
            <Dna size={14} />
          </Button>
        </Tooltip>

        <Tooltip content="Аналитика токенов">
          <Button size="icon" variant="ghost" onClick={onAnalyticsClick}>
            <BarChart3 size={14} />
          </Button>
        </Tooltip>
      </div>
    </div>
    </>
  );
}
