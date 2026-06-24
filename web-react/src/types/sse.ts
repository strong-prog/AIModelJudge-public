// ── SSE event types from agentic_stream + routes.py ──

export interface RunStartedEvent {
  type: "run.started";
  runId: string;
  sessionId: string;
  input: string;
}

export interface RunCompletedEvent {
  type: "run.completed";
  runId: string;
  sessionId: string;
  stopReason: string;
  usage: Record<string, number>;
  messages: Array<{ role: string; content: string }>;
}

export interface RunFailedEvent {
  type: "run.failed";
  runId: string;
  sessionId: string;
  stopReason: string;
  error: string;
  usage: Record<string, number>;
}

export interface PhaseEvent {
  type: "phase";
  phase: "analyze" | "consult" | "synthesize" | "apply" | "plan";
  message?: string;
}

export interface PromptEvent {
  type: "prompt";
  text: string;
}

export interface CompactNotification {
  type: "compact_notification";
  dropped_messages: number;
  remaining_messages: number;
  trigger: string;
}

export interface SummaryReceived {
  type: "summary_received";
  dropped_messages: number;
  remaining_messages: number;
  summary: string;
}

// ── Central model events ──
export interface MessageStartedEvent {
  type: "message.started";
  message: { id: string; role: string; model: string };
}

export interface ThinkingStart { type: "thinking_start" }
export interface ThinkingEnd { type: "thinking_end" }
export interface ThinkingToken {
  type: "thinking_token";
  token: string;
}

export interface ReasoningAvailable {
  type: "reasoning.available";
  thinking: string;
}

export interface TextStart { type: "text_start" }
export interface TextEnd { type: "text_end" }
export interface TextToken {
  type: "text_token";
  token: string;
}

export interface ToolStart {
  type: "tool_start";
  name: string;
  input: Record<string, unknown>;
}

export interface ToolToken {
  type: "tool_token";
  token: string;
}

export interface ToolEnd {
  type: "tool_end";
  name: string;
}

// ── Tool confirm flow ──
export interface ToolConfirmEvent {
  type: "tool_confirm";
  tool_use_id: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
  label?: string;
}

export interface ToolExecuting {
  type: "tool_executing";
  tool_use_id: string;
}

export interface ToolResultEvent {
  type: "tool_result";
  tool_use_id: string;
  name?: string;
  label?: string;
  content?: string;
  result?: string;
  duration_ms?: number;
  error?: string;
}

// ── Side model events (left/right panels) ──
export interface SideThinkingToken {
  type: "primary_thinking_token";
  panel: "left" | "right";
  model?: string;
  token: string;
}

export interface SideToolStart {
  type: "primary_tool_start";
  panel: "left" | "right";
  model?: string;
  /** Backend sends "name" */
  tool_name?: string;
  name?: string;
  label?: string;
  tool_input?: Record<string, unknown>;
  input?: Record<string, unknown>;
}

export interface SideToolEnd {
  type: "primary_tool_end";
  panel: "left" | "right";
  model?: string;
  tool_name?: string;
  name?: string;
  label?: string;
  input?: Record<string, unknown>;
  result?: string;
}

export interface SideTextToken {
  type: "primary_text_token";
  panel: "left" | "right";
  model?: string;
  token: string;
}

export interface SideError {
  type: "primary_error";
  panel: "left" | "right";
  model?: string;
  error?: string;
  message?: string;
}

export interface SideDone {
  type: "primary_done";
  panel: "left" | "right";
  model?: string;
  content?: string;
  reasoning_content?: string;
  elapsed_ms?: number;
  usage?: Record<string, unknown>;
}

// ── Synthesis events ──
export interface SynthesisEvent {
  type: "synthesis";
  phase:
    | "consensus_start"
    | "consensus_chunk"
    | "contradictions_start"
    | "contradictions_chunk"
    | "gaps_start"
    | "gaps_chunk"
    | "ideal_solution_start"
    | "ideal_solution_chunk";
  data?: string;
  token?: string;
}

// ── Subagent events ──
export interface SubagentStart {
  type: "subagent_start";
  id: string;
  task: string;
}

export interface SubagentUpdate {
  type: "subagent_update";
  id: string;
  status: string;
  data?: string;
}

export interface SubagentEnd {
  type: "subagent_end";
  id: string;
  result?: string;
  error?: string;
}

// ── Kanban events ──
export interface KanbanTaskCreated {
  type: "kanban_task_created";
  task: {
    id: string;
    title: string;
    column: string;
  };
}

export interface KanbanTaskMoved {
  type: "kanban_task_moved";
  task_id: string;
  from_column: string;
  to_column: string;
}

export interface KanbanTaskUpdated {
  type: "kanban_task_updated";
  task: { id: string; title: string; column?: string };
}

// ── Done / Error ──
export interface DoneEvent {
  type: "done";
  stop_reason: "end_turn" | "tool_use" | "max_rounds" | "cancelled" | "refusal" | string;
  usage?: Record<string, number>;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

// ── Heartbeat ──
export interface StreamingHeartbeat {
  type: "streaming_heartbeat";
}

// ── Upload ──
export interface UploadResult {
  type: "upload_result";
  files: Array<{ name: string; size: number; path: string }>;
}

// ── Plan ──
export interface PlanEvent {
  type: "plan";
  entries: Array<{ step: string; status: string }>;
}

// ── Company Mode: specialist events ──
export interface SpecialistStartEvent {
  type: "specialist.start";
  specialist: string;
  role?: string;
}

export interface SpecialistThinkingEvent {
  type: "specialist.thinking" | "specialist.text_token";
  specialist: string;
  token?: string;
  phase?: string;
}

export interface SpecialistToolStartEvent {
  type: "specialist.tool_start";
  specialist: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
}

export interface SpecialistToolEndEvent {
  type: "specialist.tool_end";
  specialist: string;
  tool_name?: string;
  result?: string;
}

export interface SpecialistDoneEvent {
  type: "specialist.done";
  specialist: string;
  content?: string;
  reasoning_content?: string;
  elapsed_ms?: number;
}

export interface SpecialistErrorEvent {
  type: "specialist.error";
  specialist: string;
  message?: string;
}

// ── Company Mode: orchestrator events ──
export interface CompanyStatusEvent {
  type: "company.status";
  phase: string;
  specialists?: string[];
  total_count?: number;
}

export interface CompanyCheckpointEvent {
  type: "company.checkpoint";
  phase: string;
  specialists_completed?: number;
  message?: string;
}

export interface CompanySynthesisEvent {
  type: "company.synthesis";
  phase: string;
  message?: string;
  content?: string;
  token?: string;
}

// ── Dev Mode: agent events ──
export interface AgentConnectedEvent {
  type: "agent.connected";
  version?: string;
  project_root?: string;
}

export interface AgentDisconnectedEvent {
  type: "agent.disconnected";
}

export interface AgentExecutingEvent {
  type: "agent.executing";
  tool: string;
  path?: string;
}

// ── Union type ──
export type SSEEvent =
  | RunStartedEvent
  | RunCompletedEvent
  | RunFailedEvent
  | PhaseEvent
  | PromptEvent
  | CompactNotification
  | SummaryReceived
  | MessageStartedEvent
  | ThinkingStart
  | ThinkingEnd
  | ThinkingToken
  | ReasoningAvailable
  | TextStart
  | TextEnd
  | TextToken
  | ToolStart
  | ToolToken
  | ToolEnd
  | ToolConfirmEvent
  | ToolExecuting
  | ToolResultEvent
  | SideThinkingToken
  | SideToolStart
  | SideToolEnd
  | SideTextToken
  | SideError
  | SideDone
  | SynthesisEvent
  | SubagentStart
  | SubagentUpdate
  | SubagentEnd
  | KanbanTaskCreated
  | KanbanTaskMoved
  | KanbanTaskUpdated
  | DoneEvent
  | ErrorEvent
  | StreamingHeartbeat
  | UploadResult
  | PlanEvent
  | SpecialistStartEvent
  | SpecialistThinkingEvent
  | SpecialistToolStartEvent
  | SpecialistToolEndEvent
  | SpecialistDoneEvent
  | SpecialistErrorEvent
  | CompanyStatusEvent
  | CompanyCheckpointEvent
  | CompanySynthesisEvent
  | AgentConnectedEvent
  | AgentDisconnectedEvent
  | AgentExecutingEvent;
