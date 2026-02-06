"use client";

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  useLocalRuntime,
  AssistantRuntimeProvider,
  type ChatModelAdapter,
  type ChatModelRunOptions,
  type ChatModelRunResult,
  type ThreadAssistantMessagePart,
} from "@assistant-ui/react";

import type { ReadonlyJSONObject } from "assistant-stream/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface InterruptPayload {
  type: string;
  tool_calls: Array<{
    id: string;
    name: string;
    arguments: ReadonlyJSONObject;
  }>;
}

interface HitlContextValue {
  /** The current pending interrupt, if any. */
  pendingInterrupt: InterruptPayload | null;
  /** The thread_id for the current conversation. */
  threadId: string;
  /** Send approval/rejection feedback to resume the graph. */
  sendFeedback: (approvalData: {
    approved_ids: string[];
    rejected_ids: string[];
  }) => void;

  resetInterrupt: () => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const HitlContext = createContext<HitlContextValue | null>(null);

export function useHitl() {
  const ctx = useContext(HitlContext);
  if (!ctx) throw new Error("useHitl must be used within MyRuntimeProvider");
  return ctx;
}

// ---------------------------------------------------------------------------
// SSE parsing helpers
// ---------------------------------------------------------------------------

interface SseEvent {
  type: string;
  content?: string;
  id?: string;
  name?: string;
  arguments?: ReadonlyJSONObject;
  payload?: InterruptPayload;
  error?: string;
}

/**
 * Parse incoming SSE bytes into event objects, accumulate text + tool calls,
 * and yield full content snapshots for the LocalRuntime.
 */
async function* parseSseStream(
  response: Response,
  onInterrupt: (payload: InterruptPayload) => void,
): AsyncGenerator<ChatModelRunResult> {
  if (!response.body) {
    throw new Error("Response body is null");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  let buffer = "";
  let accumulatedText = "";
  const toolCalls = new Map<
    string,
    {
      toolCallId: string;
      toolName: string;
      args: ReadonlyJSONObject;
      argsText: string;
    }
  >();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const dataStr = line.slice(6).trim();
        if (!dataStr || dataStr === "[DONE]") continue;

        let evt: SseEvent;
        try {
          evt = JSON.parse(dataStr);
        } catch {
          continue;
        }

        if (evt.type === "token" && evt.content) {
          accumulatedText += evt.content;
        } else if (evt.type === "tool_call" && evt.id && evt.name) {
          const args = evt.arguments ?? ({} as ReadonlyJSONObject);
          toolCalls.set(evt.id, {
            toolCallId: evt.id,
            toolName: evt.name,
            args,
            argsText: JSON.stringify(args),
          });
        } else if (evt.type === "tool_result") {
          // Tool results are handled server-side; we could surface them
          // but the LLM follow-up will describe the result anyway.
        } else if (evt.type === "interrupt" && evt.payload) {
          // HITL: yield pending tool calls with requires-action status, then stop
          onInterrupt(evt.payload);

          const parts: ThreadAssistantMessagePart[] = [];
          if (accumulatedText) {
            parts.push({ type: "text" as const, text: accumulatedText });
          }
          for (const tc of toolCalls.values()) {
            parts.push({ type: "tool-call" as const, ...tc });
          }
          // Also add the pending approval tool calls from the interrupt
          for (const tc of evt.payload.tool_calls) {
            if (!toolCalls.has(tc.id)) {
              const args = tc.arguments ?? ({} as ReadonlyJSONObject);
              parts.push({
                type: "tool-call" as const,
                toolCallId: tc.id,
                toolName: tc.name,
                args,
                argsText: JSON.stringify(args),
              });
            }
          }

          yield {
            content: parts,
            status: {
              type: "requires-action" as const,
              reason: "interrupt" as const,
            },
          };
          return;
        } else if (evt.type === "error") {
          yield {
            content: [
              {
                type: "text" as const,
                text: `Error: ${evt.error ?? "Unknown error"}`,
              },
            ],
            status: { type: "incomplete" as const, reason: "error" as const },
          };
          return;
        } else if (evt.type === "done") {
          // Normal completion - will exit the while loop
          continue;
        }

        // Yield full content snapshot after each meaningful event
        const parts: ThreadAssistantMessagePart[] = [];
        if (accumulatedText) {
          parts.push({ type: "text" as const, text: accumulatedText });
        }
        for (const tc of toolCalls.values()) {
          parts.push({ type: "tool-call" as const, ...tc });
        }
        if (parts.length > 0) {
          yield { content: parts };
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// ---------------------------------------------------------------------------
// Runtime Provider
// ---------------------------------------------------------------------------

export function MyRuntimeProvider({ children }: { children: ReactNode }) {
  const [pendingInterrupt, setPendingInterrupt] =
    useState<InterruptPayload | null>(null);

  // Persistent thread_id for the session
  const threadIdRef = useRef<string>(crypto.randomUUID());

  // Ref to hold pending feedback for the next run() call
  const pendingFeedbackRef = useRef<{
    approved_ids: string[];
    rejected_ids: string[];
  } | null>(null);

  // Ref to hold the runtime for programmatic message appending
  const runtimeRef = useRef<ReturnType<typeof useLocalRuntime> | null>(null);

  const sendFeedback = useCallback(
    (approvalData: { approved_ids: string[]; rejected_ids: string[] }) => {
      pendingFeedbackRef.current = approvalData;
      setPendingInterrupt(null);

      // Trigger a new run by appending a synthetic user message
      if (runtimeRef.current) {
        const approvedCount = approvalData.approved_ids.length;
        const rejectedCount = approvalData.rejected_ids.length;
        let msg = "";
        if (approvedCount > 0 && rejectedCount === 0) {
          msg = "Approved the requested action.";
        } else if (rejectedCount > 0 && approvedCount === 0) {
          msg = "Rejected the requested action.";
        } else {
          msg = `Approved ${approvedCount} and rejected ${rejectedCount} actions.`;
        }

        runtimeRef.current.thread.append({
          role: "user",
          content: [{ type: "text", text: msg }],
        });
      }
    },
    [],
  );

  const resetInterrupt = useCallback(() => {
    setPendingInterrupt(null);
  }, []);

  // Build the adapter with closure over shared state
  const adapterRef = useRef<ChatModelAdapter | null>(null);
  if (!adapterRef.current) {
    adapterRef.current = {
      async *run({
        messages,
        abortSignal,
      }: ChatModelRunOptions): AsyncGenerator<ChatModelRunResult> {
        const threadId = threadIdRef.current;
        const feedback = pendingFeedbackRef.current;
        pendingFeedbackRef.current = null;

        let url: string;
        let body: string;

        if (feedback) {
          // Resume from HITL interrupt
          url = "/api/be/api/v1/chat/feedback";
          body = JSON.stringify({
            thread_id: threadId,
            approval_data: feedback,
          });
        } else {
          // Normal chat stream
          const formattedMessages = messages.map((m) => {
            const text = m.content
              .filter(
                (c): c is { type: "text"; text: string } => c.type === "text",
              )
              .map((c) => c.text)
              .join("");

            if (m.role === "user") return { role: "human", content: text };
            if (m.role === "assistant") return { role: "ai", content: text };
            return { role: m.role, content: text };
          });

          url = "/api/be/api/v1/chat/stream";
          body = JSON.stringify({
            messages: formattedMessages,
            thread_id: threadId,
          });
        }

        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          signal: abortSignal,
        });

        if (!response.ok) {
          const errorText = await response.text().catch(() => "Unknown error");
          yield {
            content: [
              {
                type: "text" as const,
                text: `Backend error (${response.status}): ${errorText}`,
              },
            ],
            status: { type: "incomplete" as const, reason: "error" as const },
          };
          return;
        }

        yield* parseSseStream(response, (payload) => {
          setPendingInterrupt(payload);
        });
      },
    };
  }

  const runtime = useLocalRuntime(adapterRef.current);
  runtimeRef.current = runtime;

  return (
    <HitlContext.Provider
      value={{
        pendingInterrupt,
        threadId: threadIdRef.current,
        sendFeedback,
        resetInterrupt,
      }}
    >
      <AssistantRuntimeProvider runtime={runtime}>
        {children}
      </AssistantRuntimeProvider>
    </HitlContext.Provider>
  );
}
