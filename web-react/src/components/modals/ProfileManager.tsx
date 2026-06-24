import { useState, useEffect, useCallback } from "react";
import { useAppContext } from "@/context/AppContext";
import { listProfiles, createProfile, updateProfile, deleteProfile, activateProfile } from "@/lib/api";
import type { Profile } from "@/types/models";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { X, Plus, Star, Trash2, Edit3, Check, Settings, MessageSquare, Zap } from "lucide-react";

interface ProfileManagerProps {
  onClose: () => void;
}

interface ProfileForm {
  name: string;
  description: string;
  tools_codegraph: boolean;
  tools_memory: boolean;
  tools_web: boolean;
  ha_enabled: boolean;
}

const emptyForm: ProfileForm = {
  name: "",
  description: "",
  tools_codegraph: true,
  tools_memory: true,
  tools_web: true,
  ha_enabled: false,
};

export function ProfileManager({ onClose }: ProfileManagerProps) {
  const { state, dispatch } = useAppContext();
  const { activeProfile, availableProfiles } = state;
  const maxProfiles = 999;

  const [profiles, setProfiles] = useState<Profile[]>(availableProfiles);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState<ProfileForm>(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await listProfiles();
      setProfiles(res.profiles);
      dispatch({
        type: "SET_PROFILE",
        profile: res.active || activeProfile,
        profiles: res.profiles,
      });
    } catch {
      // ignore
    }
  }, [dispatch, activeProfile]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleCreate = async () => {
    if (!form.name.trim()) {
      setError("Название профиля обязательно");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await createProfile({
        name: form.name.trim(),
        description: form.description.trim(),
        tools: [
          ...(form.tools_codegraph ? ["codegraph"] : []),
          ...(form.tools_memory ? ["memory"] : []),
          ...(form.tools_web ? ["web_search"] : []),
        ],
        ha_enabled: form.ha_enabled,
      });
      setShowNew(false);
      setForm(emptyForm);
      await refresh();
    } catch (e: any) {
      const msg = e?.message || String(e);
      setError(msg.includes("409") ? "Профиль с таким именем уже существует" : msg);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdate = async (profileId: string) => {
    if (!form.name.trim()) {
      setError("Название обязательно");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await updateProfile(profileId, {
        name: form.name.trim(),
        description: form.description.trim(),
        tools: [
          ...(form.tools_codegraph ? ["codegraph"] : []),
          ...(form.tools_memory ? ["memory"] : []),
          ...(form.tools_web ? ["web_search"] : []),
        ],
        ha_enabled: form.ha_enabled,
      });
      setEditingId(null);
      setForm(emptyForm);
      await refresh();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (profileId: string) => {
    if (!confirm("Удалить профиль? Это действие необратимо.")) return;
    try {
      await deleteProfile(profileId);
      await refresh();
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  };

  const handleSwitch = async (profileId: string) => {
    try {
      await activateProfile(profileId);
      localStorage.setItem("amj-profile", profileId);
      dispatch({ type: "SET_PROFILE", profile: profileId });
      await refresh();
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  };

  const handleSetDefault = async (profileId: string) => {
    try {
      await activateProfile(profileId);
      await refresh();
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  };

  const startEdit = (p: Profile) => {
    setEditingId(p.id);
    setShowNew(false);
    const tools = p.tools || [];
    setForm({
      name: p.name,
      description: p.description || "",
      tools_codegraph: tools.includes("codegraph"),
      tools_memory: tools.includes("memory"),
      tools_web: tools.includes("web_search"),
      ha_enabled: p.ha_enabled || false,
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setShowNew(false);
    setForm(emptyForm);
    setError("");
  };

  return (
    <div
      className="modal-overlay"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        className="modal-content"
        style={{
          background: "var(--surface)",
          borderRadius: "var(--radius-lg)",
          padding: "24px",
          minWidth: "480px",
          maxWidth: "560px",
          maxHeight: "80vh",
          overflow: "auto",
          boxShadow: "var(--shadow-xl)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <h2 style={{ fontSize: "1.1rem", fontWeight: 600, color: "var(--text-bright)", margin: 0 }}>
            Профили
          </h2>
          <Button size="icon" variant="ghost" onClick={onClose}>
            <X size={16} />
          </Button>
        </div>

        {error && (
          <div style={{ color: "var(--red)", fontSize: "0.8rem", marginBottom: "8px", padding: "4px 8px", background: "var(--surface-hover)", borderRadius: "4px" }}>
            {error}
          </div>
        )}

        {/* Profile list */}
        {profiles.map((p) => (
          <div key={p.id} style={{
            display: "flex", alignItems: "center", gap: "8px", padding: "8px",
            border: p.id === activeProfile ? "1px solid var(--accent)" : "1px solid var(--border)",
            borderRadius: "var(--radius-sm)", marginBottom: "6px",
            background: editingId === p.id ? "var(--surface-hover)" : "var(--bg)",
          }}>
            {editingId === p.id ? (
              <ProfileFormFields form={form} setForm={setForm} userTier="business" />
            ) : (
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                  <span style={{ fontWeight: 600, fontSize: "0.85rem", color: "var(--text-bright)" }}>
                    {p.name}
                  </span>
                  {p.is_default && <Star size={12} style={{ color: "var(--accent)" }} />}
                  {p.id === activeProfile && (
                    <Badge variant="accent">активный</Badge>
                  )}
                  {p.ha_enabled && (
                    <Badge variant="default" title="Hermes Agent включён"><Zap size={10} /> HA</Badge>
                  )}
                </div>
                {p.description && (
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "2px" }}>
                    {p.description}
                  </div>
                )}
                <div style={{ display: "flex", gap: "10px", marginTop: "2px", fontSize: "0.65rem", color: "var(--text-muted)" }}>
                  {(p.session_count ?? 0) > 0 && (
                    <span><MessageSquare size={10} /> {p.session_count} чатов</span>
                  )}
                  {p.tools && p.tools.length > 0 && (
                    <span>Инструменты: {p.tools.join(", ")}</span>
                  )}
                </div>
              </div>
            )}

            <div style={{ display: "flex", gap: "2px", flexShrink: 0 }}>
              {editingId === p.id ? (
                <>
                  <Button size="icon" variant="ghost" onClick={() => handleUpdate(p.id)} disabled={loading}>
                    <Check size={14} />
                  </Button>
                  <Button size="icon" variant="ghost" onClick={cancelEdit}>
                    <X size={14} />
                  </Button>
                </>
              ) : (
                <>
                  {p.id !== activeProfile && (
                    <Button size="icon" variant="ghost" title="Переключиться" onClick={() => handleSwitch(p.id)}>
                      <Check size={14} />
                    </Button>
                  )}
                  <Button size="icon" variant="ghost" title="Редактировать" onClick={() => startEdit(p)}>
                    <Edit3 size={13} />
                  </Button>
                  {!p.is_default && (
                    <>
                      <Button size="icon" variant="ghost" title="Сделать по умолчанию" onClick={() => handleSetDefault(p.id)}>
                        <Star size={13} />
                      </Button>
                      <Button size="icon" variant="ghost" title="Удалить" onClick={() => handleDelete(p.id)}>
                        <Trash2 size={13} />
                      </Button>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        ))}

        {/* New profile form */}
        {showNew ? (
          <div style={{
            padding: "8px", border: "1px dashed var(--accent)", borderRadius: "var(--radius-sm)",
            marginBottom: "6px", background: "var(--surface-hover)",
          }}>
            <ProfileFormFields form={form} setForm={setForm} userTier="business" />
            <div style={{ display: "flex", gap: "4px", marginTop: "8px" }}>
              <Button size="sm" variant="default" onClick={handleCreate} disabled={loading}>
                Создать
              </Button>
              <Button size="sm" variant="ghost" onClick={cancelEdit}>
                Отмена
              </Button>
            </div>
          </div>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => { setShowNew(true); setEditingId(null); setForm(emptyForm); setError(""); }}>
            <Plus size={14} /> Новый профиль
          </Button>
        )}
      </div>
    </div>
  );
}

function ProfileFormFields({
  form,
  setForm,
  userTier,
}: {
  form: ProfileForm;
  setForm: (updater: (prev: ProfileForm) => ProfileForm) => void;
  userTier: string;
}) {
  const update = (patch: Partial<ProfileForm>) => setForm((prev) => ({ ...prev, ...patch }));

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "6px" }}>
      <input
        placeholder="Название профиля"
        value={form.name}
        onChange={(e) => update({ name: e.target.value })}
        style={{
          padding: "4px 8px", borderRadius: "4px", border: "1px solid var(--border)",
          background: "var(--bg)", color: "var(--text)", fontSize: "0.8rem",
        }}
      />
      <input
        placeholder="Описание"
        value={form.description}
        onChange={(e) => update({ description: e.target.value })}
        style={{
          padding: "4px 8px", borderRadius: "4px", border: "1px solid var(--border)",
          background: "var(--bg)", color: "var(--text)", fontSize: "0.78rem",
        }}
      />
      <div style={{ display: "flex", gap: "12px", fontSize: "0.75rem", color: "var(--text-muted)", flexWrap: "wrap" }}>
        <label style={{ display: "flex", alignItems: "center", gap: "4px", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={form.tools_codegraph}
            onChange={(e) => update({ tools_codegraph: e.target.checked })}
          />
          CodeGraph
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: "4px", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={form.tools_memory}
            onChange={(e) => update({ tools_memory: e.target.checked })}
          />
          Memory
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: "4px", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={form.tools_web}
            onChange={(e) => update({ tools_web: e.target.checked })}
          />
          Web Search
        </label>
        <label
          style={{ display: "flex", alignItems: "center", gap: "4px", cursor: "pointer" }}
          title="ECC-навыки из ~/.hermes/skills/ecc-imports/ будут добавлены в system prompt"
        >
          <input
            type="checkbox"
            checked={form.ha_enabled}
            onChange={(e) => update({ ha_enabled: e.target.checked })}
          />
          Hermes Agent
        </label>
      </div>
    </div>
  );
}
