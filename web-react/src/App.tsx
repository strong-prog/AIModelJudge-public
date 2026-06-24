import { useState, useCallback, useEffect } from "react";
import { ThemeProvider } from "@/context/ThemeContext";
import { AppProvider, useAppContext } from "@/context/AppContext";
import { AuthProvider, useAuth } from "@/context/AuthContext";

// Layout
import { AppLayout } from "@/components/layout/AppLayout";
import { ChatScreen } from "@/components/layout/ChatScreen";
import { ChatHeader } from "@/components/layout/ChatHeader";

// Chat
import { ChatContainer } from "@/components/chat/ChatContainer";
import { MessageInput } from "@/components/chat/MessageInput";

// Panels
import { PanelContainer } from "@/components/panels/PanelContainer";
import { PanelStream } from "@/components/panels/PanelStream";
import { SynthesisPanel } from "@/components/panels/SynthesisPanel";
import { SpecialistPanel } from "@/components/company/SpecialistPanel";
import { SynthesisPanelV2 } from "@/components/company/SynthesisPanelV2";
import type { SpecialistRole } from "@/types/models";

// Nav
import { Navigator } from "@/components/nav/Navigator";

// Views
import { KanbanBoard } from "@/components/views/KanbanBoard";
import { AnalyticsView } from "@/components/views/AnalyticsView";

// Modals
import { ApproveModal } from "@/components/modals/ApproveModal";
import { SettingsModal } from "@/components/modals/SettingsModal";
import { SelfLearningModal } from "@/components/modals/SelfLearningModal";
import { SessionModal } from "@/components/modals/SessionModal";
import { SaveSkillModal } from "@/components/modals/SaveSkillModal";
import { LoginModal } from "@/components/modals/LoginModal";
import { AccountModal } from "@/components/modals/AccountModal";
import { AgentInstallModal } from "@/components/modals/AgentInstallModal";
import { SpecialistSelector } from "@/components/company/SpecialistSelector";

// Hooks
import { useSSE } from "@/hooks/useSSE";
import { useResize } from "@/hooks/useResize";
import { uploadFiles } from "@/lib/api";
import { getModelCurrent } from "@/lib/api";

// Icons
import { Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";

function AppShell() {
  const { state, dispatch } = useAppContext();
  const { send, abort } = useSSE();
  const { user, showLogin, loading: authLoading } = useAuth();

  const { skillCandidate } = state;
  const maxSides = 2;

  const specialistDisplayNames: Record<SpecialistRole, string> = {
    marketer: "Маркетолог",
    lawyer: "Юрист",
    accountant: "Бухгалтер",
    devops: "DevOps",
  };

  // Sync user tier from AuthContext → AppContext
  useEffect(() => {
    if (user) {
      dispatch({ type: "SET_USER_TIER", tier: user.tier });
    }
  }, [user, dispatch]);

  // Initialize model on mount
  useEffect(() => {
    getModelCurrent()
      .then((current) => {
        dispatch({
          type: "SET_MODEL_ALL",
          model: { center: current.model, left: current.model, right: current.model },
        });
      })
      .catch(() => {});
  }, [dispatch]);

  // Sync comfort mode to DOM
  useEffect(() => {
    if (state.comfortMode) {
      document.documentElement.setAttribute("data-comfort", "true");
    } else {
      document.documentElement.removeAttribute("data-comfort");
    }
    localStorage.setItem("amj-comfort", String(state.comfortMode));
  }, [state.comfortMode]);

  // Restore comfort mode from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem("amj-comfort");
    if (saved === "true") {
      dispatch({ type: "TOGGLE_COMFORT", enabled: true });
    }
  }, [dispatch]);

  // Panel resize
  const navResize = useResize({
    defaultSize: 170,
    minSize: 100,
    maxSize: 350,
    onResize: (w) => dispatch({ type: "SET_NAV_WIDTH", width: w }),
  });

  const leftResize = useResize({
    defaultSize: 260,
    minSize: 40,
    maxSize: 500,
  });

  const rightResize = useResize({
    defaultSize: 260,
    minSize: 40,
    maxSize: 500,
  });

  // Modals
  const [showSettings, setShowSettings] = useState(false);
  const [showSelfLearning, setShowSelfLearning] = useState(false);
  const [showAnalytics, setShowAnalytics] = useState(false);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [showSaveSkill, setShowSaveSkill] = useState(false);
  const [saveSkillContent, setSaveSkillContent] = useState("");
  const [showAccount, setShowAccount] = useState(false);
  const [showSpecialistSelector, setShowSpecialistSelector] = useState(false);

  // Upload
  const handleUpload = useCallback(
    async (files: FileList) => {
      try {
        const result = await uploadFiles(Array.from(files));
        dispatch({ type: "SET_UPLOADED_FILES", files: result.files });
      } catch {}
    },
    [dispatch]
  );

  const handleRemoveFile = useCallback(
    (index: number) => {
      dispatch({
        type: "SET_UPLOADED_FILES",
        files: state.uploadedFiles.filter((_, i) => i !== index),
      });
    },
    [dispatch, state.uploadedFiles]
  );

  // Synthesis sections (separate from side panel streaming)
  const [synthesisSections, setSynthesisSections] = useState<
    Array<{ title: string; content: string; icon: string }>
  >([]);

  // Save-as-skill
  const handleSaveSkill = useCallback((content: string) => {
    setSaveSkillContent(content);
    setShowSaveSkill(true);
  }, []);

  const handleSaveCandidate = useCallback(() => {
    setSaveSkillContent("");
    setShowSaveSkill(true);
  }, []);

  const handleSkillCreated = useCallback(() => {
    dispatch({ type: "SET_SKILL_CANDIDATE", candidate: null });
  }, [dispatch]);

  // SSE dispatcher override for side panels — we use a separate listener
  // In a full implementation, SSE events would be routed through context.
  // For now the side panel content updates happen through the SSE hook.

  if (authLoading) {
    return (
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        height: "100vh", background: "var(--bg)", color: "var(--text-muted)",
        fontSize: "0.85rem",
      }}>
        Загрузка...
      </div>
    );
  }

  return (
    <>
    <AppLayout
      nav={
        <Navigator
          onSessionClick={(id) => setSelectedSession(id)}
        />
      }
      onNavResize={navResize.onMouseDown}
      leftPanel={
        state.panelLeftState !== "closed" && (
          state.companyMode ? (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "6px",
                padding: "6px",
                background: "var(--bg)",
                borderRight: "1px solid var(--border)",
                width: leftResize.size ?? 260,
                flexShrink: 0,
                overflow: "auto",
              }}
            >
              {state.companySpecialists.map((spec) => (
                <SpecialistPanel
                  key={spec}
                  specialist={spec}
                  displayName={specialistDisplayNames[spec] || spec}
                  events={state.companySpecialistEvents[spec] || []}
                  streaming={state.streaming}
                />
              ))}
            </div>
          ) : (
            <PanelContainer
              panel="left"
              modelName={state.model.left || "Expert A"}
            >
              <PanelStream content={state.sideLeftContent} toolActivity={state.sideLeftTools} />
            </PanelContainer>
          )
        )
      }
      onLeftResize={state.panelLeftState !== "closed" ? leftResize.onMouseDown : undefined}
      chat={
        <ChatScreen
          header={
            <ChatHeader
              onMemoryGraphClick={() => dispatch({ type: "SET_NAV_TAB", tab: "memory" })}
              onSelfLearningClick={() => setShowSelfLearning(true)}
              onAnalyticsClick={() => setShowAnalytics(!showAnalytics)}
              onTierClick={() => setShowAccount(true)}
              onSpecialistClick={() => setShowSpecialistSelector(true)}
            />
          }
          input={
            <MessageInput
              disabled={state.streaming}
              uploadedFiles={state.uploadedFiles}
              onSend={send}
              onUpload={handleUpload}
              onRemoveFile={handleRemoveFile}
            />
          }
        >
          <ChatContainer messages={state.messages} streaming={state.streaming} onSaveSkill={handleSaveSkill} skillCandidate={skillCandidate} onSaveCandidate={handleSaveCandidate} />
          <KanbanBoard visible={!!state.messages.length} />
          <AnalyticsView visible={showAnalytics} />
        </ChatScreen>
      }
      onRightResize={state.panelRightState !== "closed" ? rightResize.onMouseDown : undefined}
      rightPanel={
        state.panelRightState !== "closed" && (
          state.companyMode ? (
            <PanelContainer
              panel="right"
              modelName="Архитектор"
            >
              <SynthesisPanelV2 sections={state.companySynthesis} streaming={state.streaming} />
            </PanelContainer>
          ) : state.phase === "synthesize" ? (
            <PanelContainer
              panel="right"
              modelName="Синтез"
            >
              <SynthesisPanel
                sections={synthesisSections}
                streaming={state.streaming}
              />
            </PanelContainer>
          ) : (
            <PanelContainer
              panel="right"
              modelName={state.model.right || "Expert B"}
            >
              <PanelStream content={state.sideRightContent} toolActivity={state.sideRightTools} />
            </PanelContainer>
          )
        )
      }
    />

    {/* Modals */}
    <ApproveModal />
    <AgentInstallModal />
    <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} />
    <SelfLearningModal open={showSelfLearning} onClose={() => setShowSelfLearning(false)} />
    <SessionModal
      open={!!selectedSession}
      sessionId={selectedSession}
      onClose={() => setSelectedSession(null)}
    />
    <SaveSkillModal
      open={showSaveSkill}
      onClose={() => setShowSaveSkill(false)}
      defaultContent={saveSkillContent}
      candidate={skillCandidate}
      onCreated={handleSkillCreated}
    />
    <LoginModal />
    <AccountModal
      open={showAccount}
      onClose={() => setShowAccount(false)}
    />
    <SpecialistSelector
      open={showSpecialistSelector}
      onClose={() => setShowSpecialistSelector(false)}
    />

    {/* Floating settings button */}
    <div style={{ position: "fixed", bottom: "12px", right: "12px", zIndex: 100 }}>
      <Tooltip content="Настройки">
        <Button
          size="icon"
          variant="ghost"
          onClick={() => setShowSettings(true)}
          style={{
            background: "var(--card)",
            border: "1px solid var(--border)",
            boxShadow: "var(--shadow)",
          }}
        >
          <Settings size={16} />
        </Button>
      </Tooltip>
    </div>
    </>
  );
}

export function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <AppProvider>
          <AppShell />
        </AppProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
