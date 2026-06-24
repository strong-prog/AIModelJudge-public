import { useState, useEffect } from "react";
import { useAppContext } from "@/context/AppContext";
import { getAgentStatus } from "@/lib/api";
import { X, Check, Loader2, ExternalLink } from "lucide-react";

export function AgentInstallModal() {
  const { state, dispatch } = useAppContext();
  const [checking, setChecking] = useState(false);
  const [installCopied, setInstallCopied] = useState(false);

  // Poll agent status when modal is visible
  useEffect(() => {
    if (!state.devMode || state.agentConnected) return;
    const interval = setInterval(() => {
      setChecking(true);
      getAgentStatus()
        .then((status) => {
          dispatch({
            type: "SET_AGENT_STATUS",
            connected: status.connected,
            version: status.version,
            projectRoot: status.project_root,
          });
        })
        .catch(() => {})
        .finally(() => setChecking(false));
    }, 5000);
    return () => clearInterval(interval);
  }, [state.devMode, state.agentConnected, dispatch]);

  // Do not show if dev mode is off or agent is connected
  if (!state.devMode || state.agentConnected) return null;

  const handleDismiss = () => {
    dispatch({ type: "TOGGLE_DEV_MODE", enabled: false });
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(
      "curl -sSL https://raw.githubusercontent.com/strong-prog/AIModelJudge/main/services/hermes-local-agent/install.sh | bash"
    ).then(() => {
      setInstallCopied(true);
      setTimeout(() => setInstallCopied(false), 3000);
    }).catch(() => {});
  };

  return (
    <div className="amj-modal-overlay" onClick={handleDismiss}>
      <div className="amj-modal-content" style={{ maxWidth: "520px" }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem", color: "var(--text-bright)" }}>Dev Mode</h2>
          <button onClick={handleDismiss} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: 0 }}>
            <X size={18} />
          </button>
        </div>

        <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "16px", lineHeight: 1.6 }}>
          Dev Mode позволяет AIModelJudge работать с вашей локальной машиной вместо сервера.
          Все операции (файлы, git, тесты) выполняются на вашем компьютере, а не на сервере.
        </div>

        {/* Connection status */}
        <div style={{
          display: "flex", alignItems: "center", gap: "8px",
          padding: "10px 14px",
          borderRadius: "8px",
          background: "var(--surface-hover)",
          marginBottom: "16px",
          fontSize: "0.82rem",
        }}>
          {checking ? (
            <Loader2 size={16} style={{ animation: "spin 1s linear infinite", color: "var(--text-muted)" }} />
          ) : (
            <X size={16} style={{ color: "var(--danger)" }} />
          )}
          <span style={{ color: "var(--text-bright)" }}>Агент не подключен</span>
          {checking && <span style={{ color: "var(--text-muted)" }}>Проверка...</span>}
        </div>

        {/* Install instructions */}
        <div style={{ marginBottom: "16px" }}>
          <div style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--text-bright)", marginBottom: "8px" }}>
            Установка локального агента
          </div>
          <div style={{
            background: "#1a1a2e",
            borderRadius: "8px",
            padding: "12px 14px",
            fontFamily: "monospace",
            fontSize: "0.75rem",
            color: "#e0e0e0",
            overflowX: "auto",
            whiteSpace: "nowrap",
            marginBottom: "8px",
          }}>
            $ curl -sSL https://raw.githubusercontent.com/strong-prog/AIModelJudge/main/services/hermes-local-agent/install.sh | bash
          </div>
          <button
            onClick={handleCopy}
            style={{
              fontSize: "0.75rem",
              background: "var(--surface-hover)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "4px 12px",
              cursor: "pointer",
              color: installCopied ? "var(--accent)" : "var(--text-muted)",
              display: "inline-flex",
              alignItems: "center",
              gap: "4px",
            }}
          >
            {installCopied ? <Check size={14} /> : null}
            {installCopied ? "Скопировано" : "Скопировать команду"}
          </button>
        </div>

        {/* Or use FSAA fallback */}
        <div style={{
          padding: "10px 14px",
          borderRadius: "8px",
          background: "var(--surface-hover)",
          fontSize: "0.8rem",
          color: "var(--text-muted)",
          lineHeight: 1.5,
        }}>
          <strong style={{ color: "var(--text-bright)" }}>Браузерный доступ (FSAA)</strong>
          <br />
          В Chrome/Edge можно дать доступ к папке без установки агента.
          Без shell-доступа, только файловые операции.
        </div>

        {/* Connection info */}
        <div style={{
          marginTop: "16px",
          fontSize: "0.72rem",
          color: "var(--text-muted)",
          lineHeight: 1.6,
        }}>
          <div style={{ marginBottom: "4px" }}>
            <ExternalLink size={12} style={{ display: "inline", marginRight: "4px" }} />
            Агент подключается к <code style={{ background: "var(--surface-hover)", padding: "1px 4px", borderRadius: "3px" }}>{window.location.host}</code>
          </div>
          <div>
            Все действия логируются в <code style={{ background: "var(--surface-hover)", padding: "1px 4px", borderRadius: "3px" }}>~/.hermes-agent/audit.jsonl</code>
          </div>
        </div>
      </div>
    </div>
  );
}
