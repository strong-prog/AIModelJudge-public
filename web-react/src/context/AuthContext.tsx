import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { postLogin, postRegister, getAuthMe, postLogout } from "@/lib/api";
import type { UserInfo } from "@/types/api";

interface AuthState {
  apiKey: string | null;
  accessToken: string | null;
  user: UserInfo | null;
  loading: boolean;
  showLogin: boolean;
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, referralCode?: string) => Promise<{ onboarding_prompt?: string | null }>;
  logout: () => Promise<void>;
  dismissLogin: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    apiKey: localStorage.getItem("amj-api-key"),
    accessToken: localStorage.getItem("amj-access-token"),
    user: null,
    loading: true,
    showLogin: false,
  });

  const saveAuth = useCallback((apiKey: string, accessToken?: string, refreshToken?: string) => {
    localStorage.setItem("amj-api-key", apiKey);
    if (accessToken) localStorage.setItem("amj-access-token", accessToken);
    if (refreshToken) localStorage.setItem("amj-refresh-token", refreshToken);
    setState((s) => ({ ...s, apiKey, accessToken: accessToken || s.accessToken }));
  }, []);

  const checkAuth = useCallback(async () => {
    const accessToken = localStorage.getItem("amj-access-token");
    const apiKey = localStorage.getItem("amj-api-key");
    if (!accessToken && !apiKey) {
      setState((s) => ({ ...s, loading: false, showLogin: true }));
      return;
    }
    try {
      const user = await getAuthMe();
      setState((s) => ({ ...s, user, loading: false, showLogin: false }));
    } catch {
      // Try refresh if we have a refresh token
      const refreshToken = localStorage.getItem("amj-refresh-token");
      if (refreshToken) {
        try {
          const { postRefreshToken } = await import("@/lib/api");
          const refreshed = await postRefreshToken({ refresh_token: refreshToken });
          localStorage.setItem("amj-access-token", refreshed.access_token);
          localStorage.setItem("amj-refresh-token", refreshed.refresh_token);
          const user = await getAuthMe();
          setState((s) => ({ ...s, user, loading: false, showLogin: false, accessToken: refreshed.access_token }));
          return;
        } catch {
          // Refresh failed — clear everything
        }
      }
      // Auth invalid — prompt re-login
      localStorage.removeItem("amj-api-key");
      localStorage.removeItem("amj-access-token");
      localStorage.removeItem("amj-refresh-token");
      setState({ apiKey: null, accessToken: null, user: null, loading: false, showLogin: true });
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await postLogin({ email, password });
    saveAuth(res.api_key, res.access_token, res.refresh_token);
    setState((s) => ({
      ...s,
      user: { user_id: res.user_id, email: res.email, tier: res.tier, api_key: res.api_key, subscription_active: false },
      loading: false,
      showLogin: false,
    }));
  }, [saveAuth]);

  const register = useCallback(async (email: string, password: string, referralCode?: string) => {
    const res = await postRegister({ email, password, referral_code: referralCode || undefined });
    saveAuth(res.api_key, res.access_token, res.refresh_token);
    setState((s) => ({
      ...s,
      user: { user_id: res.user_id, email: res.email, tier: res.tier, api_key: res.api_key, subscription_active: false },
      loading: false,
      showLogin: false,
    }));
    return { onboarding_prompt: res.onboarding_prompt ?? null };
  }, [saveAuth]);

  const logout = useCallback(async () => {
    try {
      await postLogout();
    } catch {
      // ignore network errors on logout
    }
    localStorage.removeItem("amj-api-key");
    localStorage.removeItem("amj-access-token");
    localStorage.removeItem("amj-refresh-token");
    setState({ apiKey: null, accessToken: null, user: null, loading: false, showLogin: true });
  }, []);

  const dismissLogin = useCallback(() => {
    setState((s) => ({ ...s, showLogin: false }));
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, register, logout, dismissLogin }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export { AuthContext };
