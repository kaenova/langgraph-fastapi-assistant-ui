"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
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
  useAuiEvent,
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
  /** Tool-call decisions for the current interrupt. */
  decisions: Record<string, "approved" | "rejected">;
  /** Set a decision for a tool call. */
  setDecision: (id: string, decision: "approved" | "rejected") => void;
  /** Whether all pending tool calls are decided. */
  allDecided: boolean;
  /** Submit approvals/rejections to resume the graph. */
  submitDecisions: () => void;
  /** Known tool results keyed by tool call id. */
  toolResults: Record<string, { result: unknown; isError?: boolean }>;
  /** The thread_id for the current conversation. */
  threadId: string;
  /** Reset any pending interrupt UI state. */
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
  tool_call_id?: string;
  name?: string;
  arguments?: ReadonlyJSONObject;
  payload?: InterruptPayload;
  error?: string;
  is_error?: boolean;
}

/**
 * Parse incoming SSE bytes into event objects, accumulate text + tool calls,
 * and yield full content snapshots for the LocalRuntime.
 */
async function* parseSseStream(
  response: Response,
  {
    onInterrupt,
    onToolResult,
  }: {
    onInterrupt: (payload: InterruptPayload) => void;
    onToolResult: (
      toolCallId: string,
      result: unknown,
      isError?: boolean,
    ) => void;
  },
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
      result?: unknown;
      isError?: boolean;
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
          const toolCallId = evt.tool_call_id ?? evt.id;
          if (toolCallId) {
            const result = evt.content ?? null;
            const isError = evt.is_error ?? false;
            const existing = toolCalls.get(toolCallId);
            if (existing) {
              existing.result = result;
              existing.isError = isError;
            }
            onToolResult(toolCallId, result, isError);
          }
        } else if (evt.type === "interrupt" && evt.payload) {
          // HITL: yield pending tool calls with requires-action status, then stop
          onInterrupt(evt.payload);

          const parts: ThreadAssistantMessagePart[] = [];
          if (accumulatedText) {
            parts.push({ type: "text" as const, text: accumulatedText });
          }
          for (const tc of toolCalls.values()) {
            parts.push({
              type: "tool-call" as const,
              ...tc,
              ...(tc.result !== undefined ? { result: tc.result } : {}),
              ...(tc.isError !== undefined ? { isError: tc.isError } : {}),
            });
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
          parts.push({
            type: "tool-call" as const,
            ...tc,
            ...(tc.result !== undefined ? { result: tc.result } : {}),
            ...(tc.isError !== undefined ? { isError: tc.isError } : {}),
          });
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
  const pendingInterruptMessageIdRef = useRef<string | null>(null);
  const [decisions, setDecisions] = useState<
    Record<string, "approved" | "rejected">
  >({});
  const [toolResults, setToolResults] = useState<
    Record<string, { result: unknown; isError?: boolean }>
  >({});

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
      setDecisions({});

      const parentId = pendingInterruptMessageIdRef.current;
      pendingInterruptMessageIdRef.current = null;
      if (runtimeRef.current && parentId) {
        runtimeRef.current.thread.startRun({ parentId });
      }
    },
    [],
  );

  const resetInterrupt = useCallback(() => {
    setPendingInterrupt(null);
    pendingInterruptMessageIdRef.current = null;
    setDecisions({});
  }, []);

  const pendingToolCalls = pendingInterrupt?.tool_calls ?? [];
  const allDecided = useMemo(() => {
    if (pendingToolCalls.length === 0) return false;
    return pendingToolCalls.every((tc) => tc.id in decisions);
  }, [pendingToolCalls, decisions]);

  const submitDecisions = useCallback(() => {
    if (!pendingInterrupt) return;
    if (!allDecided) return;
    sendFeedback({
      approved_ids: pendingToolCalls
        .filter((tc) => decisions[tc.id] === "approved")
        .map((tc) => tc.id),
      rejected_ids: pendingToolCalls
        .filter((tc) => decisions[tc.id] === "rejected")
        .map((tc) => tc.id),
    });
  }, [pendingInterrupt, allDecided, pendingToolCalls, decisions, sendFeedback]);

  useEffect(() => {
    setDecisions({});
  }, [pendingInterrupt]);

  // Build the adapter with closure over shared state
  const adapterRef = useRef<ChatModelAdapter | null>(null);
  if (!adapterRef.current) {
    adapterRef.current = {
      async *run({
        messages,
        abortSignal,
        unstable_assistantMessageId,
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

        yield* parseSseStream(response, {
          onInterrupt: (payload) => {
            pendingInterruptMessageIdRef.current =
              unstable_assistantMessageId ?? null;
            setPendingInterrupt(payload);
          },
          onToolResult: (toolCallId, result, isError) => {
            setToolResults((prev) => {
              if (prev[toolCallId]) return prev;
              return { ...prev, [toolCallId]: { result, isError } };
            });
          },
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
        decisions,
        setDecision: (id, decision) => {
          setDecisions((prev) => ({ ...prev, [id]: decision }));
        },
        allDecided,
        submitDecisions,
        toolResults,
        threadId: threadIdRef.current,
        resetInterrupt,
      }}
    >
      <AssistantRuntimeProvider runtime={runtime}>
        <HitlComposerListener onSend={resetInterrupt} />
        {children}
      </AssistantRuntimeProvider>
    </HitlContext.Provider>
  );
}

function HitlComposerListener({ onSend }: { onSend: () => void }) {
  useAuiEvent("composer.send", () => {
    onSend();
  });
  return null;
}
