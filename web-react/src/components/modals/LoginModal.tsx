import { useState, useEffect, type FormEvent } from "react";
import { useAuth } from "@/context/AuthContext";

interface LoginModalProps {
  // If AuthContext handles showLogin, this can be self-contained
}

export function LoginModal({}: LoginModalProps) {
  const { login, register, dismissLogin, showLogin } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refCode, setRefCode] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const ref = params.get("ref");
    if (ref) {
      setRefCode(ref);
      setIsRegister(true);
    }
  }, []);

  if (!showLogin) return null;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (isRegister) {
        const result = await register(email, password, refCode || undefined);
        if (result.onboarding_prompt) {
          sessionStorage.setItem("amj-onboarding-prompt", result.onboarding_prompt);
        }
      } else {
        await login(email, password);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      // Try to extract JSON error from message
      try {
        const parsed = JSON.parse(msg.replace("API /auth/", "").split("failed")[1]?.trim() || "");
        setError(parsed.error || msg);
      } catch {
        setError(msg.includes("401") ? "Неверный email или пароль" : msg.includes("409") ? "Email уже зарегистрирован" : msg);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="modal-overlay"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.6)",
        backdropFilter: "blur(4px)",
      }}
    >
      <div
        className="modal-content"
        style={{
          background: "var(--card)",
          border: "1px solid var(--border)",
          borderRadius: "12px",
          padding: "32px",
          width: "360px",
          maxWidth: "90vw",
          boxShadow: "var(--shadow)",
        }}
      >
        <h2 style={{ margin: "0 0 4px", fontSize: "1.2rem", color: "var(--text)" }}>
          {isRegister ? "Регистрация" : "Вход"}
        </h2>
        <p style={{ margin: "0 0 20px", fontSize: "0.8rem", color: "var(--muted)" }}>
          {isRegister ? "Создайте аккаунт для доступа к AIModelJudge" : "Войдите в свой аккаунт"}
        </p>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: "12px" }}>
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              className="input-area"
              style={{
                width: "100%",
                padding: "10px 12px",
                borderRadius: "6px",
                border: "1px solid var(--border)",
                background: "var(--bg)",
                color: "var(--text)",
                fontSize: "0.9rem",
                boxSizing: "border-box",
              }}
            />
          </div>
          <div style={{ marginBottom: "16px" }}>
            <input
              type="password"
              placeholder="Пароль (минимум 6 символов)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              className="input-area"
              style={{
                width: "100%",
                padding: "10px 12px",
                borderRadius: "6px",
                border: "1px solid var(--border)",
                background: "var(--bg)",
                color: "var(--text)",
                fontSize: "0.9rem",
                boxSizing: "border-box",
              }}
            />
          </div>

          {error && (
            <div style={{ color: "#ef4444", fontSize: "0.8rem", marginBottom: "12px" }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            style={{
              width: "100%",
              padding: "10px",
              background: "var(--accent)",
              color: "#fff",
              border: "none",
              borderRadius: "6px",
              fontSize: "0.9rem",
              cursor: busy ? "wait" : "pointer",
              opacity: busy ? 0.7 : 1,
              fontWeight: 500,
            }}
          >
            {busy ? "..." : isRegister ? "Зарегистрироваться" : "Войти"}
          </button>
        </form>

        <div style={{ marginTop: "16px", textAlign: "center" }}>
          <button
            onClick={() => { setIsRegister(!isRegister); setError(""); }}
            style={{
              background: "none",
              border: "none",
              color: "var(--accent)",
              cursor: "pointer",
              fontSize: "0.8rem",
              textDecoration: "underline",
            }}
          >
            {isRegister ? "Уже есть аккаунт? Войти" : "Нет аккаунта? Зарегистрироваться"}
          </button>
        </div>

        <div style={{ marginTop: "8px", textAlign: "center" }}>
          <button
            onClick={dismissLogin}
            style={{
              background: "none",
              border: "none",
              color: "var(--muted)",
              cursor: "pointer",
              fontSize: "0.75rem",
            }}
          >
            Продолжить без входа (Free)
          </button>
        </div>
      </div>
    </div>
  );
}
