import { useCallback, useRef } from "react";
import type { SSEEvent, ToolConfirmEvent } from "@/types/sse";
import type { ChatMessage } from "@/types/models";
import { createChatRequest, createCompanyChatRequest, postApprove, getSkillsCandidate } from "@/lib/api";
import { readSSEStream } from "@/lib/sse";
import { useAppContext, useSSEDispatcher } from "@/context/AppContext";

let messageCounter = 0;
function nextId(): string {
  return `msg_${Date.now()}_${++messageCounter}`;
}

export function useSSE() {
  const { state, dispatch } = useAppContext();
  const sseDispatcher = useSSEDispatcher();
  const abortRef = useRef<AbortController | null>(null);
  const streamSessionRef = useRef<string | null>(null);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    dispatch({ type: "SET_STREAMING", streaming: false, sessionId: null });
  }, [dispatch]);

  const send = useCallback(
    async (message: string) => {
      abortRef.current?.abort();

      const controller = new AbortController();
      abortRef.current = controller;

      dispatch({ type: "CLEAR_MESSAGES" });
      if (state.companyMode) {
        dispatch({ type: "CLEAR_COMPANY_SPECIALIST_EVENTS" });
      } else {
        dispatch({ type: "CLEAR_SIDE_PANELS" });
      }
      dispatch({ type: "SET_STREAMING", streaming: true, sessionId: null });

      const userMsg: ChatMessage = {
        id: nextId(),
        role: "user",
        content: message,
        timestamp: Date.now(),
      };
      dispatch({ type: "ADD_MESSAGE", message: userMsg });

      const assistantMsg: ChatMessage = {
        id: nextId(),
        role: "assistant",
        content: "",
        timestamp: Date.now(),
      };
      dispatch({ type: "ADD_MESSAGE", message: assistantMsg });

      const sideTools = state.sideToolsEnabled.left || state.sideToolsEnabled.right
        ? (state.sideToolsEnabled.left && state.sideToolsEnabled.right ? "all"
          : state.sideToolsEnabled.left ? "codegraph" : "memory")
        : "none";

      const primaryModels = [state.model.left, state.model.right].filter(
        (m) => m && m.trim().toLowerCase() !== "off" && m.trim().toLowerCase() !== "выключено" && m.trim().toLowerCase() !== "none"
      );

      const req = state.companyMode
        ? createCompanyChatRequest({
            message,
            signal: controller.signal,
            specialists: state.companySpecialists,
            profileId: state.activeProfile || undefined,
          })
        : createChatRequest({
            message,
            signal: controller.signal,
            projectPath: state.activeProjectPath || undefined,
            sideTools,
            primaryModels,
            profileId: state.activeProfile || undefined,
            devMode: state.devMode || undefined,
          });

      // Local accumulators — avoid stale closure over state.messages
      let textAcc = "";
      let thinkingAcc = "";

      try {
        for await (const event of readSSEStream(req)) {
          sseDispatcher(event);

          if (event.type === "run.started") {
            streamSessionRef.current = event.sessionId;
            dispatch({ type: "SET_STREAMING", streaming: true, sessionId: event.sessionId });
          }

          if (event.type === "tool_confirm") {
            // Normalize backend field names (name→tool_name, input→tool_input)
            const normalizedEvent = {
              type: "tool_confirm" as const,
              tool_use_id: event.tool_use_id,
              tool_name: (event as any).name || (event as any).tool_name || "unknown",
              tool_input: (event as any).input || (event as any).tool_input || {},
              label: (event as any).label || ((event as any).name ? `Вызываю ${(event as any).name}` : "Неизвестный инструмент"),
            };
            const decision = await new Promise<"approve" | "deny" | "allow_all">((resolve) => {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              dispatch({ type: "SET_PENDING_CONFIRM", event: normalizedEvent, resolver: resolve as (d: unknown) => void });
            });
            dispatch({ type: "SET_PENDING_CONFIRM", event: null, resolver: null });
            await postApprove(
              {
                tool_use_id: event.tool_use_id,
                decision,
              },
              streamSessionRef.current ?? undefined
            );
            continue;
          }

          if (event.type === "text_token") {
            textAcc += event.token;
            dispatch({
              type: "UPDATE_LAST_MESSAGE",
              update: { content: textAcc },
            });
          }

          if (event.type === "thinking_token") {
            thinkingAcc += event.token;
            dispatch({
              type: "UPDATE_LAST_MESSAGE",
              update: { thinking: thinkingAcc },
            });
          }

          if (event.type === "tool_start") {
            dispatch({
              type: "UPDATE_LAST_MESSAGE",
              update: {
                toolUse: {
                  tool_use_id: event.name + "_" + Date.now(),
                  tool_name: event.name,
                  tool_input: event.input,
                },
              },
            });
          }

          if (event.type === "tool_result") {
            dispatch({
              type: "UPDATE_LAST_MESSAGE",
              update: {
                toolResult: {
                  tool_use_id: event.tool_use_id,
                  content: event.result || event.content || "",
                },
              },
            });
          }

          if (event.type === "phase") {
            dispatch({ type: "SET_PHASE", phase: event.phase });
          }
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        const msg = err instanceof Error ? err.message : String(err);
        dispatch({
          type: "ADD_MESSAGE",
          message: {
            id: nextId(),
            role: "system",
            content: `Error: ${msg}`,
            timestamp: Date.now(),
          },
        });
      } finally {
        const completedId = streamSessionRef.current;
        dispatch({ type: "SET_STREAMING", streaming: false, sessionId: null });
        dispatch({ type: "SET_PHASE", phase: null });
        abortRef.current = null;
        if (completedId) {
          getSkillsCandidate(completedId)
            .then((res) => {
              if (res.candidate) {
                dispatch({ type: "SET_SKILL_CANDIDATE", candidate: res.candidate });
              }
            })
            .catch(() => {});
        }
      }
    },
    [state.sideToolsEnabled, state.activeProjectPath, state.model.left, state.model.right, state.companyMode, state.companySpecialists, state.activeProfile, state.devMode, dispatch, sseDispatcher]
  );

  return { send, abort, streaming: state.streaming };
}
