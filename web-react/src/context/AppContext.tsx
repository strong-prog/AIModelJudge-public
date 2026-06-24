import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";
import type { SSEEvent, ToolConfirmEvent } from "@/types/sse";
import type { ChatMessage, CapsMap, ModelSelection, PanelState, Profile, SkillCandidate, SpecialistRole, SpecialistEvent } from "@/types/models";

// ── State shape ──

export interface SideToolEvent {
  tool_name: string;
  status: "running" | "done";
  input?: Record<string, unknown>;
  result?: string;
}

export interface CompanySynthesisSection {
  title: string;
  icon: string;
  items: string[];
}

export interface AppState {
  // Theme & Comfort
  comfortMode: boolean;
  // Model selection
  model: ModelSelection;
  caps: CapsMap;
  // Streaming
  streaming: boolean;
  streamSessionId: string | null;
  // Phase
  phase: string | null;
  // Chat
  messages: ChatMessage[];
  // Side panels
  panelLeftState: PanelState;
  panelRightState: PanelState;
  sideToolsEnabled: { left: boolean; right: boolean };
  sideLeftContent: string;
  sideRightContent: string;
  sideLeftThinking: string;
  sideRightThinking: string;
  sideLeftTools: SideToolEvent[];
  sideRightTools: SideToolEvent[];
  // Uploads
  uploadedFiles: Array<{ name: string; size: number; path: string }>;
  // Tool confirm
  pendingConfirm: ToolConfirmEvent | null;
  confirmResolver: ((d: unknown) => void) | null;
  // Subagents
  subagentCount: number;
  // Kanban
  kanbanUpdateVersion: number;
  // Project
  activeProjectPath: string;
  // Nav
  navCollapsed: boolean;
  navWidth: number;
  navActiveTab: string;
  // Profile
  activeProfile: string;
  availableProfiles: Profile[];
  // Auth
  userTier: string;
  // Skill candidate
  skillCandidate: SkillCandidate | null;
  // Company Mode
  companyMode: boolean;
  companySpecialists: SpecialistRole[];
  companySpecialistEvents: Record<string, SpecialistEvent[]>;
  companySynthesis: CompanySynthesisSection[];
  // Dev Mode (local agent)
  devMode: boolean;
  agentConnected: boolean;
  agentVersion: string | null;
  agentProjectRoot: string | null;
}

const initialState: AppState = {
  comfortMode: false,
  model: { center: "", left: "", right: "" },
  caps: { center: [], left: [], right: [] },
  streaming: false,
  streamSessionId: null,
  phase: null,
  messages: [],
  panelLeftState: "open",
  panelRightState: "open",
  sideToolsEnabled: { left: true, right: true },
  sideLeftContent: "",
  sideRightContent: "",
  sideLeftThinking: "",
  sideRightThinking: "",
  sideLeftTools: [],
  sideRightTools: [],
  uploadedFiles: [],
  pendingConfirm: null,
  confirmResolver: null,
  subagentCount: 0,
  kanbanUpdateVersion: 0,
  activeProjectPath: "",
  navCollapsed: false,
  navWidth: 170,
  navActiveTab: "sessions",
  activeProfile: "aimodeljudge",
  availableProfiles: [],
  userTier: "free",
  skillCandidate: null,
  companyMode: false,
  companySpecialists: [],
  companySpecialistEvents: {},
  companySynthesis: [],
  devMode: false,
  agentConnected: false,
  agentVersion: null,
  agentProjectRoot: null,
};

// ── Actions ──

export type AppAction =
  | { type: "SET_MODEL"; panel: "center" | "left" | "right"; modelId: string }
  | { type: "SET_MODEL_ALL"; model: ModelSelection }
  | { type: "SET_CAPS"; caps: CapsMap }
  | { type: "SET_STREAMING"; streaming: boolean; sessionId?: string | null }
  | { type: "SET_PHASE"; phase: string | null }
  | { type: "ADD_MESSAGE"; message: ChatMessage }
  | { type: "UPDATE_LAST_MESSAGE"; update: Partial<ChatMessage> }
  | { type: "SET_MESSAGES"; messages: ChatMessage[] }
  | { type: "CLEAR_MESSAGES" }
  | { type: "SET_PANEL_LEFT"; state: PanelState }
  | { type: "SET_PANEL_RIGHT"; state: PanelState }
  | { type: "SET_SIDE_TOOLS"; panel: "left" | "right"; enabled: boolean }
  | { type: "SET_UPLOADED_FILES"; files: AppState["uploadedFiles"] }
  | { type: "SET_PENDING_CONFIRM"; event: ToolConfirmEvent | null; resolver?: ((d: unknown) => void) | null }
  | { type: "INCREMENT_SUBAGENTS" }
  | { type: "DECREMENT_SUBAGENTS" }
  | { type: "SET_SUBAGENT_COUNT"; count: number }
  | { type: "SET_KANBAN_VERSION"; version: number }
  | { type: "SET_ACTIVE_PROJECT"; path: string }
  | { type: "SET_NAV_COLLAPSED"; collapsed: boolean }
  | { type: "SET_NAV_WIDTH"; width: number }
  | { type: "SET_NAV_TAB"; tab: string }
  | { type: "TOGGLE_COMFORT"; enabled: boolean }
  | { type: "SET_PROFILE"; profile: string; profiles?: AppState["availableProfiles"] }
  | { type: "SET_USER_TIER"; tier: string }
  | { type: "SET_SKILL_CANDIDATE"; candidate: SkillCandidate | null }
  | { type: "SIDE_APPEND"; panel: "left" | "right"; field: "content" | "thinking"; token: string }
  | { type: "SIDE_TOOL_START"; panel: "left" | "right"; tool: SideToolEvent }
  | { type: "SIDE_TOOL_END"; panel: "left" | "right"; toolName: string; result?: string }
  | { type: "SIDE_ERROR"; panel: "left" | "right"; message: string }
  | { type: "CLEAR_SIDE_PANELS" }
  | { type: "TOGGLE_COMPANY_MODE"; enabled: boolean }
  | { type: "SET_COMPANY_SPECIALISTS"; specialists: SpecialistRole[] }
  | { type: "COMPANY_SPECIALIST_EVENT"; specialist: string; event: SpecialistEvent }
  | { type: "CLEAR_COMPANY_SPECIALIST_EVENTS" }
  | { type: "SET_COMPANY_SYNTHESIS"; sections: CompanySynthesisSection[] }
  | { type: "TOGGLE_DEV_MODE"; enabled: boolean }
  | { type: "SET_AGENT_STATUS"; connected: boolean; version?: string | null; projectRoot?: string | null };

function reducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "SET_MODEL":
      return { ...state, model: { ...state.model, [action.panel]: action.modelId } };
    case "SET_MODEL_ALL":
      return { ...state, model: action.model };
    case "SET_CAPS":
      return { ...state, caps: action.caps };
    case "SET_STREAMING":
      return {
        ...state,
        streaming: action.streaming,
        streamSessionId: action.sessionId ?? state.streamSessionId,
      };
    case "SET_PHASE":
      return { ...state, phase: action.phase };
    case "ADD_MESSAGE":
      return { ...state, messages: [...state.messages, action.message] };
    case "UPDATE_LAST_MESSAGE": {
      const msgs = [...state.messages];
      if (msgs.length > 0) {
        msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], ...action.update };
      }
      return { ...state, messages: msgs };
    }
    case "SET_MESSAGES":
      return { ...state, messages: action.messages };
    case "CLEAR_MESSAGES":
      return { ...state, messages: [] };
    case "SET_PANEL_LEFT":
      return { ...state, panelLeftState: action.state };
    case "SET_PANEL_RIGHT":
      return { ...state, panelRightState: action.state };
    case "SET_SIDE_TOOLS":
      return {
        ...state,
        sideToolsEnabled: { ...state.sideToolsEnabled, [action.panel]: action.enabled },
      };
    case "SET_UPLOADED_FILES":
      return { ...state, uploadedFiles: action.files };
    case "SET_PENDING_CONFIRM":
      return { ...state, pendingConfirm: action.event, confirmResolver: action.resolver ?? null };
    case "INCREMENT_SUBAGENTS":
      return { ...state, subagentCount: state.subagentCount + 1 };
    case "DECREMENT_SUBAGENTS":
      return { ...state, subagentCount: Math.max(0, state.subagentCount - 1) };
    case "SET_SUBAGENT_COUNT":
      return { ...state, subagentCount: action.count };
    case "SET_KANBAN_VERSION":
      return { ...state, kanbanUpdateVersion: action.version };
    case "SET_ACTIVE_PROJECT":
      return { ...state, activeProjectPath: action.path };
    case "SET_NAV_COLLAPSED":
      return { ...state, navCollapsed: action.collapsed };
    case "SET_NAV_WIDTH":
      return { ...state, navWidth: action.width };
    case "SET_NAV_TAB":
      return { ...state, navActiveTab: action.tab };
    case "TOGGLE_COMFORT":
      return { ...state, comfortMode: action.enabled };
    case "SET_PROFILE":
      return {
        ...state,
        activeProfile: action.profile,
        availableProfiles: action.profiles ?? state.availableProfiles,
      };
    case "SET_USER_TIER":
      return { ...state, userTier: action.tier };
    case "SET_SKILL_CANDIDATE":
      return { ...state, skillCandidate: action.candidate };
    case "SIDE_APPEND":
      if (action.field === "content") {
        return action.panel === "left"
          ? { ...state, sideLeftContent: state.sideLeftContent + action.token }
          : { ...state, sideRightContent: state.sideRightContent + action.token };
      }
      return action.panel === "left"
        ? { ...state, sideLeftThinking: state.sideLeftThinking + action.token }
        : { ...state, sideRightThinking: state.sideRightThinking + action.token };
    case "SIDE_TOOL_START":
      if (action.panel === "left") {
        return { ...state, sideLeftTools: [...state.sideLeftTools, action.tool] };
      }
      return { ...state, sideRightTools: [...state.sideRightTools, action.tool] };
    case "SIDE_TOOL_END": {
      const updateTools = (tools: SideToolEvent[]) =>
        tools.map((t) => t.tool_name === action.toolName && t.status === "running"
          ? { ...t, status: "done" as const, result: action.result }
          : t);
      if (action.panel === "left") {
        return { ...state, sideLeftTools: updateTools(state.sideLeftTools) };
      }
      return { ...state, sideRightTools: updateTools(state.sideRightTools) };
    }
    case "SIDE_ERROR": {
      const errTool: SideToolEvent = { tool_name: "error", status: "done", result: action.message };
      if (action.panel === "left") {
        return { ...state, sideLeftTools: [...state.sideLeftTools, errTool] };
      }
      return { ...state, sideRightTools: [...state.sideRightTools, errTool] };
    }
    case "CLEAR_SIDE_PANELS":
      return {
        ...state,
        sideLeftContent: "",
        sideRightContent: "",
        sideLeftThinking: "",
        sideRightThinking: "",
        sideLeftTools: [],
        sideRightTools: [],
      };
    case "TOGGLE_COMPANY_MODE":
      return { ...state, companyMode: action.enabled };
    case "SET_COMPANY_SPECIALISTS":
      return {
        ...state,
        companySpecialists: action.specialists,
        companySpecialistEvents: Object.fromEntries(
          action.specialists.map((s) => [s, [] as SpecialistEvent[]])
        ),
      };
    case "COMPANY_SPECIALIST_EVENT":
      return {
        ...state,
        companySpecialistEvents: {
          ...state.companySpecialistEvents,
          [action.specialist]: [
            ...(state.companySpecialistEvents[action.specialist] || []),
            action.event,
          ],
        },
      };
    case "CLEAR_COMPANY_SPECIALIST_EVENTS":
      return {
        ...state,
        companySpecialistEvents: Object.fromEntries(
          state.companySpecialists.map((s) => [s, [] as SpecialistEvent[]])
        ),
        companySynthesis: [],
      };
    case "SET_COMPANY_SYNTHESIS":
      return { ...state, companySynthesis: action.sections };
    case "TOGGLE_DEV_MODE":
      return { ...state, devMode: action.enabled, agentConnected: action.enabled ? state.agentConnected : false };
    case "SET_AGENT_STATUS":
      return {
        ...state,
        agentConnected: action.connected,
        agentVersion: action.version ?? state.agentVersion,
        agentProjectRoot: action.projectRoot ?? state.agentProjectRoot,
      };
    default:
      return state;
  }
}

// ── Context ──

interface AppContextValue {
  state: AppState;
  dispatch: Dispatch<AppAction>;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const savedProfile = localStorage.getItem("amj-profile") || "aimodeljudge";
  const [state, dispatch] = useReducer(reducer, {
    ...initialState,
    activeProfile: savedProfile,
  });

  // Загружаем список профилей при старте
  useEffect(() => {
    import("@/lib/api").then((api) => {
      api.listProfiles().then((res) => {
        dispatch({ type: "SET_PROFILE", profile: savedProfile, profiles: res.profiles });
      }).catch(() => {});
    });
  }, []);

  return <AppContext.Provider value={{ state, dispatch }}>{children}</AppContext.Provider>;
}

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useAppContext must be used within AppProvider");
  return ctx;
}

// ── Convenience hooks ──

export function useAppDispatch() {
  return useAppContext().dispatch;
}

export function useAppState() {
  return useAppContext().state;
}

/** Convert SSE events into dispatch calls */
export function useSSEDispatcher() {
  const dispatch = useAppDispatch();

  return useCallback(
    (event: SSEEvent) => {
      switch (event.type) {
        case "run.started":
          dispatch({ type: "SET_STREAMING", streaming: true, sessionId: event.sessionId });
          break;
        case "run.completed":
        case "run.failed":
          dispatch({ type: "SET_STREAMING", streaming: false, sessionId: null });
          dispatch({ type: "SET_PHASE", phase: null });
          break;
        case "phase":
          dispatch({ type: "SET_PHASE", phase: event.phase });
          break;
        case "done":
          if (event.stop_reason !== "tool_use") {
            dispatch({ type: "SET_STREAMING", streaming: false, sessionId: null });
          }
          break;
        case "subagent_start":
          dispatch({ type: "INCREMENT_SUBAGENTS" });
          break;
        case "subagent_end":
          dispatch({ type: "DECREMENT_SUBAGENTS" });
          break;
        case "kanban_task_created":
        case "kanban_task_moved":
        case "kanban_task_updated":
          dispatch({ type: "SET_KANBAN_VERSION", version: Date.now() });
          break;
        // Side panel events
        case "primary_text_token":
          dispatch({ type: "SIDE_APPEND", panel: event.panel, field: "content", token: event.token });
          break;
        case "primary_thinking_token":
          dispatch({ type: "SIDE_APPEND", panel: event.panel, field: "thinking", token: event.token });
          break;
        case "primary_tool_start":
          dispatch({
            type: "SIDE_TOOL_START",
            panel: event.panel,
            tool: {
              tool_name: (event as any).name || event.tool_name || "unknown",
              status: "running",
              input: (event as any).input || event.tool_input,
            },
          });
          break;
        case "primary_tool_end":
          dispatch({
            type: "SIDE_TOOL_END",
            panel: event.panel,
            toolName: (event as any).name || event.tool_name || "unknown",
            result: event.result,
          });
          break;
        case "primary_error":
          dispatch({
            type: "SIDE_ERROR",
            panel: event.panel,
            message: (event as any).message || event.error || "Unknown error",
          });
          break;
        // Company Mode: specialist events
        case "specialist.start":
        case "specialist.thinking":
        case "specialist.text_token":
        case "specialist.tool_start":
        case "specialist.tool_end":
        case "specialist.done":
        case "specialist.error":
          dispatch({
            type: "COMPANY_SPECIALIST_EVENT",
            specialist: event.specialist,
            event: {
              type: event.type,
              specialist: event.specialist as SpecialistRole,
              content: (event as any).content || (event as any).token,
              tool_name: (event as any).tool_name,
              tool_args: (event as any).tool_input,
              tool_result: (event as any).result,
              phase: (event as any).phase,
            },
          });
          break;
        case "company.status":
          dispatch({
            type: "COMPANY_SPECIALIST_EVENT",
            specialist: "_status",
            event: {
              type: "company.status",
              specialist: "system" as SpecialistRole,
              phase: event.phase,
              content: event.specialists ? JSON.stringify(event.specialists) : undefined,
            },
          });
          break;
        case "company.checkpoint":
          // Update phase for UI
          dispatch({ type: "SET_PHASE", phase: event.phase });
          break;
        case "company.synthesis":
          if (event.phase === "starting") {
            dispatch({ type: "SET_PHASE", phase: "synthesize" });
          } else if (event.phase === "complete" && event.content) {
            const sections = parseSynthesisSections(event.content);
            dispatch({ type: "SET_COMPANY_SYNTHESIS", sections });
            dispatch({ type: "SET_PHASE", phase: null });
          }
          break;
        // Dev Mode: agent status events
        case "agent.connected":
          dispatch({
            type: "SET_AGENT_STATUS",
            connected: true,
            version: (event as any).version ?? null,
            projectRoot: (event as any).project_root ?? null,
          });
          break;
        case "agent.disconnected":
          dispatch({ type: "SET_AGENT_STATUS", connected: false });
          break;
        case "agent.executing":
          // Tool is being executed on local agent — no state change needed
          break;
      }
    },
    [dispatch]
  );
}

function parseSynthesisSections(text: string): CompanySynthesisSection[] {
  const sections: CompanySynthesisSection[] = [];
  const sectionMap: Record<string, { icon: string; title: string }> = {
    "консенсус": { icon: "✓", title: "Консенсус" },
    "противоречия": { icon: "⚡", title: "Противоречия" },
    "пробелы": { icon: "?", title: "Пробелы" },
    "план действий": { icon: "▶", title: "План действий" },
    "риски": { icon: "⚠", title: "Риски" },
    "решение": { icon: "★", title: "Решение" },
    "сводка": { icon: "📋", title: "Сводка" },
  };

  const headerRegex = /^## (.+)$/gm;
  let lastIndex = 0;
  let lastTitle = "";
  const parts: Array<{ title: string; body: string }> = [];

  let match;
  while ((match = headerRegex.exec(text)) !== null) {
    if (lastTitle) {
      parts.push({ title: lastTitle, body: text.slice(lastIndex, match.index).trim() });
    }
    lastTitle = match[1].trim();
    lastIndex = match.index + match[0].length;
  }
  if (lastTitle) {
    parts.push({ title: lastTitle, body: text.slice(lastIndex).trim() });
  }
  // Fallback: if no sections parsed, show entire text as Сводка
  if (parts.length === 0) {
    return [{ title: "Сводка", icon: "📋", items: [text.trim()] }];
  }

  for (const part of parts) {
    const key = part.title.toLowerCase();
    const info = Object.entries(sectionMap).find(([k]) => key.includes(k));
    const items = part.body
      .split("\n")
      .filter((line) => line.trim().startsWith("-") || line.trim().startsWith("*") || line.trim().match(/^\d+\./))
      .map((line) => line.replace(/^[-*\d]+\.\s*/, "").trim())
      .filter(Boolean);
    if (info) {
      sections.push({
        title: info[1].title,
        icon: info[1].icon,
        items: items.length ? items : [part.body.trim()],
      });
    }
  }

  return sections;
}
