import type { SSEEvent, ToolConfirmEvent } from "@/types/sse";

export type SSECallback = (event: SSEEvent) => void;
export type ToolConfirmCallback = (event: ToolConfirmEvent) => Promise<"approve" | "deny" | "allow_all">;

interface SSEStreamOptions {
  request: Request;
  onEvent: SSECallback;
  onToolConfirm?: ToolConfirmCallback;
}

/**
 * Read SSE stream from fetch response.
 * Yields parsed JSON events until the stream ends.
 */
export async function* readSSEStream(
  request: Request
): AsyncGenerator<SSEEvent> {
  const response = await fetch(request);

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Chat request failed (${response.status}): ${text}`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      let eventType = "";
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          const data = line.slice(6);
          if (!data || data === "[DONE]") continue;
          try {
            const parsed = JSON.parse(data);
            if (eventType) parsed._eventType = eventType;
            yield parsed as SSEEvent;
          } catch {
            // skip unparseable lines
          }
          eventType = "";
        }
      }
    }
  } finally {
    reader.cancel();
  }
}

/**
 * Manage SSE stream with abort controller and optional tool confirm callback.
 */
export function createSSEStream(options: SSEStreamOptions): {
  abort: () => void;
  promise: Promise<void>;
} {
  const abortController = new AbortController();

  const promise = (async () => {
    try {
      for await (const event of readSSEStream(options.request)) {
        options.onEvent(event);
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      const message = err instanceof Error ? err.message : String(err);
      options.onEvent({ type: "error", message });
    }
  })();

  return {
    abort: () => abortController.abort(),
    promise,
  };
}
