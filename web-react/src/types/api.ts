import type {
  CronJob,
  KanbanTask,
  MemoryGraphData,
  ModelInfo,
  ModelSelection,
  Project,
  SelfLearningStatus,
  Session,
  SessionDetail,
  Skill,
  SkillCandidate,
  SkillGraphData,
  TokenAnalytics,
} from "./models";

// ── Request types ──

export interface ChatRequest {
  message: string;
  history?: Array<{ role: string; content: string }>;
  uploads?: string[];
  model?: string;
  planMode?: boolean;
  projectPath?: string;
  sideTools?: "all" | "codegraph" | "memory" | "none";
}

export interface ApproveRequest {
  tool_use_id: string;
  decision: "approve" | "deny" | "allow_all";
}

export interface SwitchModelRequest {
  model: string;
}

export interface CreateKanbanRequest {
  title: string;
  column: string;
}

export interface CreateCronRequest {
  name: string;
  prompt: string;
  schedule: string;
  skills?: string[];
}

export interface CronToggleRequest {
  job_id: string;
  action: "pause" | "resume";
}

export interface CronTriggerRequest {
  job_id: string;
}

export interface SkillsCreateRequest {
  name: string;
  description: string;
  content: string;
  tools?: string[];
}

export interface SkillsCreateResponse {
  ok: boolean;
  name: string;
  path: string;
}

export interface SkillsRateRequest {
  path: string;
  rating: "up" | "down";
}

export interface SkillsRateResponse {
  path: string;
  rating: string;
  call_count: number;
  upvotes: number;
  downvotes: number;
}

export interface DiffRequest {
  file_path: string;
  old_content: string;
  new_content: string;
}

export interface DiffLine {
  type: "keep" | "add" | "remove";
  content: string;
}

export interface DiffHunk {
  header: string;
  lines: DiffLine[];
}

export interface DiffResponse {
  file_path: string;
  hunks: DiffHunk[];
}

// ── Response types ──

export interface HealthResponse {
  status: string;
}

export interface ModelCurrentResponse {
  model: string;
  display: string;
  other: string;
  other_display: string;
}

export interface ModelSwitchResponse {
  ok: boolean;
  center: string;
  left: string;
  right: string;
}

export interface ProjectsListResponse {
  projects: Project[];
  root: string;
}

export interface ProjectsContextResponse {
  files: number;
  dirs: number;
  size: number;
  language: string;
}

export interface SkillsListResponse {
  skills: Skill[];
  hot_skills?: Skill[];
}

export interface SkillsContentResponse {
  path: string;
  content: string;
  name: string;
  description: string;
}

export interface SkillsCandidateResponse {
  candidate: SkillCandidate | null;
}

export interface SkillsCreateFromSessionRequest {
  session_id: string;
  name?: string;
  description?: string;
  content?: string;
}

export interface SkillsAutoRankResponse {
  ranked: Array<{ path: string; hot_score: number; is_hot: boolean; call_count: number; upvotes: number; downvotes: number; suggest_delete: boolean }>;
  promoted: number;
  demoted: number;
  suggest_delete: number;
}

export interface SkillsUseRequest {
  path: string;
}

export interface SkillsGraphResponse extends SkillGraphData {}

export interface KanbanListResponse {
  tasks: KanbanTask[];
}

export interface KanbanCreateResponse {
  ok: boolean;
  task: KanbanTask;
}

export interface SessionsRecentResponse {
  sessions: Session[];
}

export interface SessionsSearchResponse {
  sessions: Session[];
  query: string;
}

export interface SessionDetailResponse extends SessionDetail {}

export interface MemoryGraphResponse extends MemoryGraphData {}

export interface AnalyticsTokensResponse extends TokenAnalytics {}

export interface SelfLearningStatusResponse extends SelfLearningStatus {}

export interface CronListResponse {
  jobs: CronJob[];
  updated_at: string;
}

export interface CronCreateResponse {
  ok: boolean;
  job_id: string;
}

export interface CronToggleResponse {
  ok: boolean;
  state: string;
}

export interface CronTriggerResponse {
  ok: boolean;
}

export interface CronDeleteResponse {
  ok: boolean;
}

export interface UploadResponse {
  ok: boolean;
  files: Array<{ name: string; size: number; path: string }>;
}

export interface ModelListResponse {
  models: ModelInfo[];
}

export interface CancelResponse {
  ok: boolean;
}

export interface ApproveResponse {
  ok: boolean;
}

// ── Profile types ──
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

export interface ProfileActivateResponse {
  ok: boolean;
  profile_id: string;
  name: string;
}

// ── Auth types ──

export interface AuthRequest {
  email: string;
  password: string;
  referral_code?: string;
}

export interface AuthResponse {
  user_id: string;
  email: string;
  api_key: string;
  tier: string;
  access_token?: string;
  refresh_token?: string;
  token_type?: string;
  expires_in?: number;
  onboarding_prompt?: string | null;
  referral_applied?: boolean;
}

export interface TokenRefreshRequest {
  refresh_token: string;
}

export interface TokenRefreshResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface ScopedApiKey {
  prefix: string;
  scope: string;
  name: string;
  created_at: string;
}

export interface ApiKeysListResponse {
  keys: ScopedApiKey[];
}

export interface CreateApiKeyRequest {
  scope: string;
  name: string;
}

export interface CreateApiKeyResponse {
  api_key: string;
  scope: string;
  name: string;
}

export interface UserInfo {
  user_id: string;
  email?: string;
  tier: string;
  api_key: string;
  subscription_active: boolean;
  is_admin?: boolean;
  scope?: string;
}

// ── Admin types ──

export interface AdminUser {
  id: string;
  email: string;
  tier: string;
  is_admin: number;
  banned: number;
  created_at: string;
}

export interface AdminUsersListResponse {
  users: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminUserDetail {
  user: Record<string, unknown>;
  subscription: Record<string, unknown> | null;
  skills_count: number;
}

export interface AdminUpdateUserRequest {
  tier?: string;
  banned?: number;
  is_admin?: number;
}

export interface AdminAuditEntry {
  ts: string;
  epoch: number;
  user_id: string;
  action: string;
  resource: string;
  detail: string;
  ip: string;
  result: string;
}

export interface AdminAuditResponse {
  entries: AdminAuditEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface PromoCode {
  id: number;
  code: string;
  discount_percent: number;
  max_uses: number;
  current_uses: number;
  expires_at: string | null;
  created_by: string | null;
  created_at: string;
  active: number;
}

export interface PromoCodesListResponse {
  promo_codes: PromoCode[];
}

export interface CreatePromoCodeRequest {
  code: string;
  discount_percent: number;
  max_uses?: number;
  expires_at?: string;
}

export interface PromoValidateResponse {
  valid: boolean;
  code?: string;
  discount_percent?: number;
  expires_at?: string;
  error?: string;
}

export interface AdminStatsOverview {
  total_users: number;
  active_subscriptions: number;
  subscriptions_by_tier: Record<string, number>;
  daily_active_users: number;
}

export interface AdminStatsResponse {
  stats: AdminStatsOverview;
}

export interface AdminConfigEntry {
  key: string;
  value: string;
  updated_at: string;
}

export interface AdminConfigResponse {
  config: AdminConfigEntry[];
}

export interface AdminConfigUpdateRequest {
  [key: string]: string;
}

// ── Subscription types ──

export interface SubscriptionStatus {
  tier: string;
  status: string;
  current_period_end?: string;
  subscription_active: boolean;
}

// ── Benchmark types ──

export interface BenchmarkBucket {
  count: number;
  total_duration_ms: number;
  total_tokens: number;
  successes: number;
  avg_duration_ms: number;
  avg_tokens: number;
  success_rate: number;
}

export interface BenchmarkDaily extends BenchmarkBucket {
  day: string;
}

export interface BenchmarkStatsResponse {
  total: number;
  avg_duration_ms: number;
  p50_duration_ms: number;
  p95_duration_ms: number;
  avg_tokens: number;
  success_rate: number;
  by_model: Record<string, BenchmarkBucket>;
  by_phase: Record<string, BenchmarkBucket>;
  daily: BenchmarkDaily[];
}

export interface BenchmarkRecentItem {
  request_id: string;
  timestamp: number;
  phase: string;
  model: string;
  tokens_in: number;
  tokens_out: number;
  duration_ms: number;
  tool_calls_count: number;
  success: boolean;
}

// ── SSE-related types ──
export interface StreamSession {
  sessionId: string;
  abortController: AbortController;
  messages: import("./models").ChatMessage[];
}
