import type {
  AdminAuditResponse,
  AdminConfigResponse,
  AdminConfigUpdateRequest,
  AdminStatsResponse,
  AdminUpdateUserRequest,
  AdminUserDetail,
  AdminUsersListResponse,
  CreatePromoCodeRequest,
  PromoCodesListResponse,
  PromoValidateResponse,
  AnalyticsTokensResponse,
  ApproveRequest,
  ApproveResponse,
  CancelResponse,
  CreateCronRequest,
  CreateKanbanRequest,
  CronCreateResponse,
  CronDeleteResponse,
  CronListResponse,
  Profile,
  CronToggleRequest,
  CronToggleResponse,
  CronTriggerRequest,
  CronTriggerResponse,
  DiffRequest,
  DiffResponse,
  HealthResponse,
  KanbanCreateResponse,
  KanbanListResponse,
  MemoryGraphResponse,
  ModelCurrentResponse,
  ModelListResponse,
  ModelSwitchResponse,
  ProjectsContextResponse,
  ProjectsListResponse,
  SelfLearningStatusResponse,
  SessionDetailResponse,
  SessionsRecentResponse,
  SessionsSearchResponse,
  SkillsAutoRankResponse,
  SkillsCandidateResponse,
  SkillsContentResponse,
  SkillsCreateFromSessionRequest,
  SkillsCreateRequest,
  SkillsCreateResponse,
  SkillsGraphResponse,
  SkillsListResponse,
  SkillsRateRequest,
  SkillsRateResponse,
  SkillsUseRequest,
  SwitchModelRequest,
  UploadResponse,
} from "@/types/api";

const BASE = ""; // Vite proxy handles routing

function getApiKey(): string {
  try {
    return localStorage.getItem("amj-api-key") || "";
  } catch {
    return "";
  }
}

function getAccessToken(): string {
  try {
    return localStorage.getItem("amj-access-token") || "";
  } catch {
    return "";
  }
}

function getRefreshToken(): string {
  try {
    return localStorage.getItem("amj-refresh-token") || "";
  } catch {
    return "";
  }
}

async function tryRefreshToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;
  try {
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem("amj-access-token", data.access_token);
    localStorage.setItem("amj-refresh-token", data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const accessToken = getAccessToken();
  const apiKey = getApiKey();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string> | undefined),
  };
  // Prefer Bearer JWT, fallback X-AMJ-API-Key
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  } else if (apiKey) {
    headers["X-AMJ-API-Key"] = apiKey;
  }

  const { headers: _, ...rest } = (options ?? {});
  let res = await fetch(`${BASE}${url}`, { ...rest, headers });

  // Auto-refresh on 401 with JWT
  if (res.status === 401 && accessToken) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      headers["Authorization"] = `Bearer ${getAccessToken()}`;
      res = await fetch(`${BASE}${url}`, { ...rest, headers });
    }
  }

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${url} failed (${res.status}): ${text}`);
  }
  return res.json();
}

// ── GET ──
export const getHealth = () => request<HealthResponse>("/health");

export const getModelCurrent = () => request<ModelCurrentResponse>("/model/current");

export const getModelList = () => request<ModelListResponse>("/model/list");

export const getProjectsList = (root = "") =>
  request<ProjectsListResponse>(`/projects/list${root ? `?root=${encodeURIComponent(root)}` : ""}`);

export const getProjectsContext = (path = "") =>
  request<ProjectsContextResponse>(`/projects/context?path=${encodeURIComponent(path)}`);

export const getSkillsList = () => request<SkillsListResponse>("/skills/list");

export const getSkillsContent = (path: string) =>
  request<SkillsContentResponse>(`/skills/content?path=${encodeURIComponent(path)}`);

export const getKanbanTasks = () => request<KanbanListResponse>("/kanban/tasks");

export const getSessionsRecent = (limit = 20) =>
  request<SessionsRecentResponse>(`/sessions/recent?limit=${limit}`);

export const getSessionsSearch = (q = "", limit = 20) =>
  request<SessionsSearchResponse>(`/sessions/search?q=${encodeURIComponent(q)}&limit=${limit}`);

export const getSession = (sessionId: string) =>
  request<SessionDetailResponse>(`/sessions/${sessionId}`);

export const getMemoryGraph = (projectId = "") =>
  request<MemoryGraphResponse>(`/memory/graph?project_id=${encodeURIComponent(projectId)}`);

export const getAnalyticsTokens = (days = 14) =>
  request<AnalyticsTokensResponse>(`/analytics/tokens?days=${days}`);

export const getSelfLearningStatus = () =>
  request<SelfLearningStatusResponse>("/selflearning/status");

export const getCronList = () => request<CronListResponse>("/cron/list");

// ── Profiles ──
export const listProfiles = () =>
  request<import("../types/api").ProfileListResponse>("/profiles/list");

// ── POST ──
export const postModelSwitch = (body: SwitchModelRequest) =>
  request<ModelSwitchResponse>("/model/switch", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const postCancel = () =>
  request<CancelResponse>("/cancel", { method: "POST" });

export const postApprove = (body: ApproveRequest, streamSession?: string) => {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (streamSession) headers["X-Stream-Session"] = streamSession;
  return request<ApproveResponse>("/approve", {
    method: "POST",
    body: JSON.stringify(body),
    headers,
  });
};

export const postKanbanCreate = (body: CreateKanbanRequest) =>
  request<KanbanCreateResponse>("/kanban/tasks", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const postCronTrigger = (body: CronTriggerRequest) =>
  request<CronTriggerResponse>("/cron/trigger", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const postCronToggle = (body: CronToggleRequest) =>
  request<CronToggleResponse>("/cron/toggle", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const postCronCreate = (body: CreateCronRequest) =>
  request<CronCreateResponse>("/cron/create", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const postSkillsCreate = (body: SkillsCreateRequest) =>
  request<SkillsCreateResponse>("/skills/create", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const postSkillsRate = (body: SkillsRateRequest) =>
  request<SkillsRateResponse>("/skills/rate", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getSkillsCandidate = (sessionId: string) =>
  request<SkillsCandidateResponse>(`/skills/candidate?session_id=${encodeURIComponent(sessionId)}`);

export const postSkillsCreateFromSession = (body: SkillsCreateFromSessionRequest) =>
  request<SkillsCreateResponse>("/skills/create-from-session", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const postSkillsAutoRank = () =>
  request<SkillsAutoRankResponse>("/skills/auto-rank", { method: "POST" });

export const postSkillsUse = (body: SkillsUseRequest) =>
  request<SkillsRateResponse>("/skills/use", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getSkillsGraph = () =>
  request<SkillsGraphResponse>("/skills/graph");

export const postDiff = (body: DiffRequest) =>
  request<DiffResponse>("/diff", {
    method: "POST",
    body: JSON.stringify(body),
  });

// ── PATCH ──
export const patchKanbanTask = (taskId: string, body: Partial<{ title: string; column: string; status: string }>) =>
  request<KanbanCreateResponse>(`/kanban/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

// ── DELETE ──
export const deleteKanbanTask = (taskId: string) =>
  request<{ ok: boolean }>(`/kanban/tasks/${taskId}`, { method: "DELETE" });

export const deleteCronJob = (jobId: string) =>
  request<CronDeleteResponse>(`/cron/${jobId}`, { method: "DELETE" });

// ── Profile Manager v2 (/profiles/*) ──

export const createProfile = (data: {
  name: string;
  description?: string;
  models?: string[];
  tools?: string[];
  ha_enabled?: boolean;
}) => request<{ ok: boolean; profile_id: string; name: string }>("/profiles/create", {
  method: "POST",
  body: JSON.stringify(data),
});

export const getProfile = (profileId: string) =>
  request<{ profile: Profile }>(`/profiles/${profileId}`);

export const updateProfile = (profileId: string, fields: Record<string, unknown>) =>
  request<{ ok: boolean }>(`/profiles/${profileId}`, {
    method: "PATCH",
    body: JSON.stringify(fields),
  });

export const deleteProfile = (profileId: string) =>
  request<{ ok: boolean }>(`/profiles/${profileId}`, { method: "DELETE" });

export const activateProfile = (profileId: string) =>
  request<{ ok: boolean; profile_id: string; name: string }>(`/profiles/${profileId}/activate`, {
    method: "POST",
  });

export const getProfileContext = (profileId: string) =>
  request<{ profile_id: string; files: Array<{ name: string; content: string; size: number }> }>(`/profiles/${profileId}/context`);

export const uploadProfileContext = (profileId: string, data: { name: string; content: string }) =>
  request<{ ok: boolean; name: string }>(`/profiles/${profileId}/context`, {
    method: "POST",
    body: JSON.stringify(data),
  });

// ── Company Mode ──

export const listCompanySpecialists = () =>
  request<{ specialists: Array<{ name: string; display_name: string; available: boolean }>; max_for_tier: number; tier: string }>("/company/specialists");

export function createCompanyChatRequest(params: {
  message: string;
  specialists: string[];
  signal: AbortSignal;
  history?: Array<{ role: string; content: string }>;
  profileId?: string;
}): Request {
  const body: Record<string, unknown> = {
    message: params.message,
    specialists: params.specialists,
  };
  if (params.history?.length) body.history = params.history;
  if (params.profileId) body.profile_id = params.profileId;

  const accessToken = getAccessToken();
  const apiKey = getApiKey();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  } else if (apiKey) {
    headers["X-AMJ-API-Key"] = apiKey;
  }

  return new Request(`${BASE}/company/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: params.signal,
  });
}

// ── Agent status ──
export interface AgentStatusResponse {
  connected: boolean;
  version: string | null;
  project_root: string | null;
}
export async function getAgentStatus(): Promise<AgentStatusResponse> {
  const accessToken = getAccessToken();
  const apiKey = getApiKey();
  const headers: Record<string, string> = {};
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  } else if (apiKey) {
    headers["X-AMJ-API-Key"] = apiKey;
  }
  const res = await fetch(`${BASE}/agent/status`, { headers });
  if (!res.ok) throw new Error(`Agent status failed (${res.status})`);
  return res.json();
}

// ── Upload (multipart) ──
export async function uploadFiles(files: File[]): Promise<UploadResponse> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const res = await fetch(`${BASE}/upload`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(`Upload failed (${res.status})`);
  return res.json();
}

// ── Chat SSE (JSON POST) ──
export function createChatRequest(params: {
  message: string;
  signal: AbortSignal;
  history?: Array<{ role: string; content: string }>;
  uploads?: string[];
  modelOverride?: string;
  planMode?: boolean;
  devMode?: boolean;
  projectPath?: string;
  sideTools?: string;
  primaryModels?: string[];
  profileId?: string;
}): Request {
  const body: Record<string, unknown> = {
    message: params.message,
    side_tools_enabled: params.sideTools === "all" ? { left: true, right: true }
      : params.sideTools === "codegraph" ? { left: true, right: false }
      : params.sideTools === "memory" ? { left: false, right: true }
      : {},
  };
  if (params.history?.length) body.history = params.history;
  if (params.uploads?.length) body.files = params.uploads;
  if (params.modelOverride) body.model = params.modelOverride;
  if (params.planMode) body.plan_mode = true;
  if (params.devMode) body.dev_mode = true;
  if (params.projectPath) body.project_path = params.projectPath;
  if (params.primaryModels?.length) body.primary_models = params.primaryModels;
  if (params.profileId) body.profile_id = params.profileId;

  const accessToken = getAccessToken();
  const apiKey = getApiKey();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  } else if (apiKey) {
    headers["X-AMJ-API-Key"] = apiKey;
  }

  return new Request(`${BASE}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: params.signal,
  });
}

// ── Auth ──

export const postRegister = (body: import("../types/api").AuthRequest) =>
  request<import("../types/api").AuthResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const postLogin = (body: import("../types/api").AuthRequest) =>
  request<import("../types/api").AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getAuthMe = () =>
  request<import("../types/api").UserInfo>("/auth/me");

export const postRefreshToken = (body: import("../types/api").TokenRefreshRequest) =>
  request<import("../types/api").TokenRefreshResponse>("/auth/refresh", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const postLogout = () =>
  request<{ ok: boolean }>("/auth/logout", { method: "POST" });

export const getApiKeys = () =>
  request<import("../types/api").ApiKeysListResponse>("/auth/api-keys");

export const postApiKey = (body: import("../types/api").CreateApiKeyRequest) =>
  request<import("../types/api").CreateApiKeyResponse>("/auth/api-keys", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const deleteApiKey = (prefix: string) =>
  request<{ ok: boolean }>(`/auth/api-keys/${prefix}`, { method: "DELETE" });

export const postRotateSecret = () =>
  request<{ ok: boolean; message: string }>("/auth/rotate-secret", { method: "POST" });

// ── Subscription ──

export const getSubscriptionStatus = () =>
  request<import("../types/api").SubscriptionStatus>("/subscription/status");

// ── Benchmarks ──

export const getBenchmarkStats = (days = 7) =>
  request<import("../types/api").BenchmarkStatsResponse>(`/benchmarks/stats?days=${days}`);

export const getBenchmarkRecent = (limit = 50) =>
  request<import("../types/api").BenchmarkRecentItem[]>(`/benchmarks/recent?limit=${limit}`);

// ── Admin ──

export const getAdminUsers = (search = "", tier = "", limit = 50, offset = 0) =>
  request<AdminUsersListResponse>(`/admin/users?search=${encodeURIComponent(search)}&tier=${encodeURIComponent(tier)}&limit=${limit}&offset=${offset}`);

export const getAdminUser = (userId: string) =>
  request<AdminUserDetail>(`/admin/users/${encodeURIComponent(userId)}`);

export const patchAdminUser = (userId: string, body: AdminUpdateUserRequest) =>
  request<{ ok: boolean; user_id: string }>(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const deleteAdminUser = (userId: string) =>
  request<{ ok: boolean; user_id: string }>(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
  });

export const getAdminAudit = (limit = 50, offset = 0, action = "", userId = "") =>
  request<AdminAuditResponse>(`/admin/audit?limit=${limit}&offset=${offset}&action=${encodeURIComponent(action)}&user_id=${encodeURIComponent(userId)}`);

export const getAdminPromoCodes = () =>
  request<PromoCodesListResponse>("/admin/promo-codes");

export const postAdminPromoCode = (body: CreatePromoCodeRequest) =>
  request<{ ok: boolean; id: number; code: string; discount_percent: number }>("/admin/promo-codes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const deleteAdminPromoCode = (promoId: number) =>
  request<{ ok: boolean; promo_id: number }>(`/admin/promo-codes/${promoId}`, {
    method: "DELETE",
  });

export const postValidatePromo = (code: string) =>
  request<PromoValidateResponse>("/promo/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });

export const getAdminStats = () =>
  request<AdminStatsResponse>("/admin/stats");

export const getAdminConfig = () =>
  request<AdminConfigResponse>("/admin/config");

export const patchAdminConfig = (body: AdminConfigUpdateRequest) =>
  request<{ ok: boolean }>("/admin/config", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
