// ── Shared model types ──

export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  caps: string;
}

export interface ModelSelection {
  center: string;
  left: string;
  right: string;
}

export interface CapsMap {
  center: string[];
  left: string[];
  right: string[];
}

export interface Session {
  id: string;
  started_at: string;
  last_active_at: string;
  project_path: string;
  model?: string;
  message_count: number;
  summary?: string;
}

export interface SessionDetail {
  id: string;
  started_at: string;
  last_active_at: string;
  project_path: string;
  model?: string;
  messages: Array<{ role: string; content: string }>;
}

export interface Skill {
  name: string;
  path: string;
  description: string;
  type: "local" | "shared" | "ecc";
  call_count: number;
  upvotes: number;
  downvotes: number;
  hot_score?: number;
  is_hot?: boolean;
}

export interface SkillCandidate {
  session_id: string;
  suggested_name: string;
  description: string;
  content: string;
  tools_used: string[];
  goal: string;
  tool_sequence: string[];
  result_summary: string;
  confidence: number;
  created_at?: string;
}

export interface SkillNode {
  id: string;
  name: string;
  path: string;
  hot_score: number;
  is_hot: boolean;
  call_count: number;
  upvotes: number;
  downvotes: number;
  description: string;
  category: string;
}

export interface SkillLink {
  source: string;
  target: string;
  type: string;
  weight: number;
}

export interface SkillGraphData {
  nodes: SkillNode[];
  edges: SkillLink[];
}

export interface Project {
  name: string;
  path: string;
}

export interface KanbanTask {
  id: string;
  title: string;
  column: "subagents" | "tasks" | "edits";
  status: string;
  created_at: string;
  updated_at: string;
}

export interface CronJob {
  id: string;
  name: string;
  schedule_display: string;
  state: "scheduled" | "paused" | "running";
  enabled: boolean;
  prompt_preview: string;
  last_run_at?: string;
  last_run_file?: string;
}

export interface SelfLearningStatus {
  skills: { local: number; shared: number; ecc: number; total: number };
  memory: {
    total: number;
    project: number;
    pattern: number;
    reference: number;
    hot: number;
    relationships: number;
  };
  hot_cache: { size: number; max: number };
  memory_budget: { used: number; limit: number; percent: number };
  last_session?: { started_at: string; project_path: string };
}

export interface MemoryNode {
  id: number;
  content: string;
  memory_type: string;
  is_hot: boolean;
  trust_score: number;
  access_count: number;
  importance_score: number;
  category: string | null;
  created_at: string;
  tags: string[];
}

export interface MemoryLink {
  source: number;
  target: number;
  type: string;
}

export interface MemoryGraphData {
  nodes: MemoryNode[];
  links: MemoryLink[] | null;
}

// ── Profile Manager v2 ──

export interface Profile {
  id: string;
  name: string;
  description: string;
  is_default: boolean;
  models: string[];
  tools: string[];
  ha_enabled: boolean;
  session_count?: number;
  created_at: string;
  updated_at: string;
}

export interface ProfileListResponse {
  profiles: Profile[];
  active: string;
}

// ── Company Mode ──

export type SpecialistRole = "marketer" | "lawyer" | "accountant" | "devops";

export interface CompanyChatRequest {
  message: string;
  specialists: SpecialistRole[];
  history?: Array<{ role: string; content: string }>;
  profileId?: string;
}

export interface SpecialistEvent {
  type: string;
  specialist: SpecialistRole;
  content?: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  tool_result?: string;
  phase?: string;
}

export interface AnalyticsDay {
  day: string;
  sessions: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  estimated_cost_usd: number;
}

export interface TokenAnalytics {
  days: AnalyticsDay[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  toolUse?: {
    tool_use_id: string;
    tool_name: string;
    tool_input: Record<string, unknown>;
  };
  toolResult?: {
    tool_use_id: string;
    content: string;
  };
  thinking?: string;
  phase?: string;
  timestamp: number;
}

export type PanelState = "open" | "minimized" | "closed";
