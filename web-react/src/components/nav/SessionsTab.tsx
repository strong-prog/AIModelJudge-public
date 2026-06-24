import { Fragment, useEffect, useState } from "react";
import { useAppContext } from "@/context/AppContext";
import { getSessionsRecent, getSessionsSearch } from "@/lib/api";
import { timeAgo, truncateMiddle } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import type { Session } from "@/types/models";

function groupSessionsByDate(sessions: Session[]): { label: string; items: Session[] }[] {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart.getTime() - 86_400_000);

  const today: Session[] = [];
  const yesterday: Session[] = [];
  const earlier: Session[] = [];

  for (const s of sessions) {
    const d = new Date(s.last_active_at);
    if (d >= todayStart) today.push(s);
    else if (d >= yesterdayStart) yesterday.push(s);
    else earlier.push(s);
  }

  const groups: { label: string; items: Session[] }[] = [];
  if (today.length) groups.push({ label: "Сегодня", items: today });
  if (yesterday.length) groups.push({ label: "Вчера", items: yesterday });
  if (earlier.length) groups.push({ label: "Ранее", items: earlier });
  return groups;
}

interface SessionsTabProps {
  onSessionClick: (sessionId: string) => void;
}

export function SessionsTab({ onSessionClick }: SessionsTabProps) {
  const { state } = useAppContext();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [favorites, setFavorites] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem("amj-favorites");
      return new Set(raw ? JSON.parse(raw) : []);
    } catch {
      return new Set();
    }
  });

  const toggleFavorite = (id: string) => {
    setFavorites((prev) => {
      const next = new Set(prev);
      prev.has(id) ? next.delete(id) : next.add(id);
      localStorage.setItem("amj-favorites", JSON.stringify([...next]));
      return next;
    });
  };

  useEffect(() => {
    (query
      ? getSessionsSearch(query, 30)
      : getSessionsRecent(30)
    )
      .then((r) => setSessions(r.sessions))
      .catch(() => {});
  }, [query]);

  const activeSessionId = activeId || state.streamSessionId;
  const groups = groupSessionsByDate(sessions);

  return (
    <div className="nav" style={{ padding: "10px" }}>
      <div className="nav-title">Сессии</div>
      <div style={{ marginBottom: "8px" }}>
        <Input
          placeholder="Поиск сессий..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="nav-scroll">
        {groups.map((group, gi) => (
          <Fragment key={group.label}>
            {gi > 0 && <div className="nav-divider" />}
            <div className="nav-group-label">{group.label}</div>
            {group.items.map((s) => (
              <div
                key={s.id}
                className={`nav-item${activeSessionId === s.id ? " active" : ""}`}
                onClick={() => {
                  setActiveId(s.id);
                  onSessionClick(s.id);
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span className="nav-item-title">
                    {favorites.has(s.id) && (
                      <span style={{ color: "var(--tool-icon)", marginRight: "3px" }}>★</span>
                    )}
                    {s.summary || truncateMiddle(s.id, 16)}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleFavorite(s.id);
                    }}
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      fontSize: "0.7rem",
                      color: favorites.has(s.id) ? "var(--tool-icon)" : "var(--muted)",
                      flexShrink: 0,
                      marginLeft: "4px",
                    }}
                  >
                    {favorites.has(s.id) ? "★" : "☆"}
                  </button>
                </div>
                <div className="nav-item-meta">
                  {s.model && <Badge variant="accent">{truncateMiddle(s.model, 14)}</Badge>}
                  <span style={{ marginLeft: s.model ? "6px" : 0 }}>{timeAgo(s.last_active_at)}</span>
                  {s.message_count > 0 && <span> · {s.message_count} msg</span>}
                </div>
                {s.project_path && (
                  <div className="nav-item-time">
                    {truncateMiddle(s.project_path, 30)}
                  </div>
                )}
              </div>
            ))}
          </Fragment>
        ))}
        {sessions.length === 0 && (
          <div style={{ color: "var(--muted)", fontSize: "0.72rem", textAlign: "center", padding: "20px" }}>
            Нет сессий
          </div>
        )}
      </div>
    </div>
  );
}
