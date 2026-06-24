import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import {
  getAdminUsers,
  patchAdminUser,
  deleteAdminUser,
  getAdminAudit,
} from "@/lib/api";
import type { AdminUser, AdminAuditEntry } from "@/types/api";

type AdminSubTab = "users" | "audit";

export function AdminTab() {
  const { user } = useAuth();
  const [subTab, setSubTab] = useState<AdminSubTab>("users");

  if (!user?.is_admin) {
    return (
      <div style={{ padding: "12px", color: "var(--muted)", fontSize: "0.72rem" }}>
        Нет доступа. Требуются права администратора.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div
        style={{
          display: "flex",
          borderBottom: "1px solid var(--border)",
          flexShrink: 0,
        }}
      >
        {(["users", "audit"] as AdminSubTab[]).map((t) => (
          <button
            key={t}
            className="nav-tab"
            onClick={() => setSubTab(t)}
            style={{
              flex: 1,
              padding: "5px 4px",
              fontSize: "0.6rem",
              background: subTab === t ? "var(--accent)" : "transparent",
              color: subTab === t ? "var(--text-on-accent)" : "var(--muted)",
              border: "none",
              cursor: "pointer",
              fontFamily: "inherit",
              whiteSpace: "nowrap",
            }}
          >
            {t === "users" ? "Пользователи" : "Аудит"}
          </button>
        ))}
      </div>
      <div style={{ flex: 1, overflow: "auto" }}>
        {subTab === "users" && <UsersSubTab />}
        {subTab === "audit" && <AuditSubTab />}
      </div>
    </div>
  );
}

function UsersSubTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const pageSize = 20;

  const loadUsers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getAdminUsers(search, "", pageSize, page * pageSize);
      setUsers(res.users);
      setTotal(res.total);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [search, page]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const toggleBan = async (u: AdminUser) => {
    try {
      await patchAdminUser(u.id, { banned: u.banned ? 0 : 1 });
      loadUsers();
    } catch {
      /* ignore */
    }
  };

  const handleDelete = async (userId: string) => {
    if (!confirm("Удалить пользователя навсегда?")) return;
    try {
      await deleteAdminUser(userId);
      loadUsers();
    } catch {
      /* ignore */
    }
  };

  const handleEdit = async (userId: string, field: string, value: unknown) => {
    try {
      await patchAdminUser(userId, { [field]: value });
      setEditId(null);
      loadUsers();
    } catch {
      /* ignore */
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div style={{ padding: "6px 8px", fontSize: "0.7rem" }}>
      <input
        type="text"
        placeholder="Поиск по email..."
        value={search}
        onChange={(e) => { setSearch(e.target.value); setPage(0); }}
        style={{
          width: "100%",
          padding: "4px 8px",
          marginBottom: "6px",
          fontSize: "0.68rem",
          background: "var(--bg)",
          color: "var(--text)",
          border: "1px solid var(--border)",
          borderRadius: "4px",
          fontFamily: "inherit",
        }}
      />
      {loading && <div style={{ color: "var(--muted)", padding: "4px 0" }}>Загрузка...</div>}
      <div style={{ marginBottom: "4px", color: "var(--muted)", fontSize: "0.6rem" }}>
        Всего: {total}
      </div>
      {users.map((u) => (
        <div
          key={u.id}
          style={{
            padding: "4px 6px",
            marginBottom: "3px",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "4px",
            fontSize: "0.65rem",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
              {u.email}
              {u.is_admin ? " ⭐" : ""}
              {u.banned ? " 🚫" : ""}
            </span>
            <span style={{ color: "var(--muted)", fontSize: "0.6rem", marginLeft: "4px" }}>{u.tier}</span>
          </div>
          {editId === u.id ? (
            <div style={{ display: "flex", gap: "3px", marginTop: "4px", flexWrap: "wrap" }}>
              <select
                defaultValue={u.tier}
                onChange={(e) => handleEdit(u.id, "tier", e.target.value)}
                style={{ fontSize: "0.6rem", padding: "1px 3px", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "3px" }}
              >
                <option value="free">Free</option>
                <option value="pro">Pro</option>
                <option value="business">Business</option>
              </select>
              <button onClick={() => handleEdit(u.id, "banned", u.banned ? 0 : 1)} style={{ fontSize: "0.6rem", padding: "1px 4px", cursor: "pointer", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "3px" }}>
                {u.banned ? "Разбанить" : "Забанить"}
              </button>
              <button onClick={() => handleEdit(u.id, "is_admin", u.is_admin ? 0 : 1)} style={{ fontSize: "0.6rem", padding: "1px 4px", cursor: "pointer", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "3px" }}>
                {u.is_admin ? "Снять админа" : "Сделать админом"}
              </button>
              <button onClick={() => setEditId(null)} style={{ fontSize: "0.6rem", padding: "1px 4px", cursor: "pointer", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "3px" }}>Отмена</button>
            </div>
          ) : (
            <div style={{ display: "flex", gap: "4px", marginTop: "3px" }}>
              <button onClick={() => setEditId(u.id)} style={{ fontSize: "0.58rem", padding: "0px 4px", cursor: "pointer", background: "transparent", color: "var(--accent)", border: "none" }}>Изменить</button>
              <button onClick={() => toggleBan(u)} style={{ fontSize: "0.58rem", padding: "0px 4px", cursor: "pointer", background: "transparent", color: "var(--warning)", border: "none" }}>
                {u.banned ? "Разбанить" : "Бан"}
              </button>
              <button onClick={() => handleDelete(u.id)} style={{ fontSize: "0.58rem", padding: "0px 4px", cursor: "pointer", background: "transparent", color: "var(--danger)", border: "none" }}>Удалить</button>
            </div>
          )}
        </div>
      ))}
      {totalPages > 1 && (
        <div style={{ display: "flex", gap: "4px", justifyContent: "center", marginTop: "6px" }}>
          <button disabled={page === 0} onClick={() => setPage(page - 1)} style={{ fontSize: "0.6rem", padding: "2px 6px", cursor: "pointer", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "3px", opacity: page === 0 ? 0.4 : 1 }}>
            ←
          </button>
          <span style={{ fontSize: "0.6rem", color: "var(--muted)", padding: "2px 4px" }}>
            {page + 1} / {totalPages}
          </span>
          <button disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)} style={{ fontSize: "0.6rem", padding: "2px 6px", cursor: "pointer", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "3px", opacity: page >= totalPages - 1 ? 0.4 : 1 }}>
            →
          </button>
        </div>
      )}
    </div>
  );
}

function AuditSubTab() {
  const [entries, setEntries] = useState<AdminAuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const pageSize = 30;

  const loadAudit = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getAdminAudit(pageSize, page * pageSize, "", "");
      setEntries(res.entries);
      setTotal(res.total);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    loadAudit();
  }, [loadAudit]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div style={{ padding: "6px 8px", fontSize: "0.7rem" }}>
      {loading && <div style={{ color: "var(--muted)", padding: "4px 0" }}>Загрузка...</div>}
      <div style={{ marginBottom: "4px", color: "var(--muted)", fontSize: "0.6rem" }}>
        Записей: {total}
      </div>
      {entries.map((e, i) => (
        <div
          key={`${e.epoch}-${i}`}
          style={{
            padding: "3px 6px",
            marginBottom: "2px",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "3px",
            fontSize: "0.6rem",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--accent)", fontWeight: 500 }}>{e.action}</span>
            <span style={{ color: "var(--muted)" }}>{e.result}</span>
          </div>
          <div style={{ color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {e.user_id} | {e.resource} | {e.detail}
          </div>
        </div>
      ))}
      {totalPages > 1 && (
        <div style={{ display: "flex", gap: "4px", justifyContent: "center", marginTop: "6px" }}>
          <button disabled={page === 0} onClick={() => setPage(page - 1)} style={{ fontSize: "0.6rem", padding: "2px 6px", cursor: "pointer", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "3px", opacity: page === 0 ? 0.4 : 1 }}>
            ←
          </button>
          <span style={{ fontSize: "0.6rem", color: "var(--muted)", padding: "2px 4px" }}>
            {page + 1} / {totalPages}
          </span>
          <button disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)} style={{ fontSize: "0.6rem", padding: "2px 6px", cursor: "pointer", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "3px", opacity: page >= totalPages - 1 ? 0.4 : 1 }}>
            →
          </button>
        </div>
      )}
    </div>
  );
}
