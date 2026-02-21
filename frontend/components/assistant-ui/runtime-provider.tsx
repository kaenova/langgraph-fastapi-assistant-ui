"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AssistantRuntimeProvider,
  unstable_useRemoteThreadListRuntime as useRemoteThreadListRuntime,
  useLocalRuntime,
  useThread,
  useThreadRuntime,
  type ChatModelAdapter,
  type ThreadHistoryAdapter,
  type ThreadAssistantMessagePart,
  type unstable_RemoteThreadListAdapter as RemoteThreadListAdapter,
} from "@assistant-ui/react";
import { createAssistantStream } from "assistant-stream";
import type { ReadonlyJSONObject } from "assistant-stream/utils";

import { Thread } from "@/components/assistant-ui/thread";

type BackendEvent =
  | { type: "text_delta"; delta: string }
  | {
      type: "tool_call";
      toolCallId: string;
      toolName: string;
      args: ReadonlyJSONObject;
      argsText?: string;
    }
  | {
      type: "tool_result";
      toolCallId: string;
      result: unknown;
      isError?: boolean;
    }
  | { type: "done"; status: "complete" | "requires-action" }
  | { type: "error"; message: string };

type HistoryRepository = {
  headId?: string | null;
  messages: Array<{
    message: Record<string, unknown>;
    parentId: string | null;
    runConfig?: Record<string, unknown>;
  }>;
};
type LocalHistoryLoadResult = Awaited<ReturnType<ThreadHistoryAdapter["load"]>>;

const THREAD_API_BASE = "/api/be/api/v1/threads";
const HUMAN_TOOL_NAMES = ["weather", "generate_image", "get_current_time"];

function toDateOrNow(value: unknown): Date {
  if (value instanceof Date) return value;
  if (typeof value === "string" || typeof value === "number") {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) return parsed;
  }
  return new Date();
}

function normalizeHistoryRepository(
  repository: HistoryRepository,
): LocalHistoryLoadResult {
  const normalizedItems = repository.messages.map((item) => ({
    parentId: item.parentId ?? null,
    runConfig: item.runConfig ?? {},
    message: {
      ...item.message,
      createdAt: toDateOrNow(item.message.createdAt),
    },
  }));

  const pending = [...normalizedItems];
  const accepted: LocalHistoryLoadResult["messages"] = [];
  const acceptedIds = new Set<string>();

  while (pending.length > 0) {
    let progressed = false;
    for (let index = 0; index < pending.length; ) {
      const item = pending[index];
      const messageRecord = item.message as Record<string, unknown>;
      const messageId =
        typeof messageRecord.id === "string" ? messageRecord.id : undefined;
      if (!messageId) {
        pending.splice(index, 1);
        progressed = true;
        continue;
      }

      if (item.parentId === null || acceptedIds.has(item.parentId)) {
        accepted.push(item as LocalHistoryLoadResult["messages"][number]);
        acceptedIds.add(messageId);
        pending.splice(index, 1);
        progressed = true;
        continue;
      }

      index += 1;
    }

    if (!progressed) {
      break;
    }
  }

  const fallbackHeadId =
    accepted.length > 0
      ? (((accepted[accepted.length - 1].message as Record<string, unknown>).id as
          | string
          | undefined) ?? null)
      : null;
  const resolvedHeadId =
    repository.headId && acceptedIds.has(repository.headId)
      ? repository.headId
      : fallbackHeadId;

  return {
    headId: resolvedHeadId,
    messages: accepted,
  };
}

async function* parseNdjsonStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<BackendEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      yield JSON.parse(trimmed) as BackendEvent;
    }
  }

  if (buffer.trim()) {
    yield JSON.parse(buffer.trim()) as BackendEvent;
  }
}

async function* parseSseStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<BackendEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let dataLines: string[] = [];

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const rawLine of lines) {
      const line = rawLine.replace(/\r$/, "");
      if (!line) {
        if (dataLines.length > 0) {
          const payload = dataLines.join("\n");
          dataLines = [];
          if (payload.trim()) {
            yield JSON.parse(payload) as BackendEvent;
          }
        }
        continue;
      }
      if (line.startsWith(":")) continue;
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
  }

  if (buffer.trim()) {
    const line = buffer.replace(/\r$/, "");
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (dataLines.length > 0) {
    const payload = dataLines.join("\n");
    if (payload.trim()) {
      yield JSON.parse(payload) as BackendEvent;
    }
  }
}

async function* parseBackendStream(
  response: Response,
): AsyncGenerator<BackendEvent> {
  if (!response.body) return;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream")) {
    yield* parseSseStream(response.body);
    return;
  }
  yield* parseNdjsonStream(response.body);
}

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || "Request failed");
  }

  return (await response.json()) as T;
}

function buildAssistantParts(
  text: string,
  toolCalls: Map<string, ThreadAssistantMessagePart>,
): ThreadAssistantMessagePart[] {
  const parts: ThreadAssistantMessagePart[] = [];
  if (text) {
    parts.push({ type: "text", text });
  }
  for (const part of toolCalls.values()) {
    parts.push(part);
  }
  return parts;
}

const InitialPromptSender = ({
  threadId,
  initialPrompt,
}: {
  threadId: string;
  initialPrompt?: string;
}) => {
  const threadRuntime = useThreadRuntime({ optional: true });
  const threadState = useThread({ optional: true });
  const sentPrompt = useRef<string | null>(null);

  useEffect(() => {
    const prompt = initialPrompt?.trim();
    if (!threadRuntime || !threadState || !prompt || sentPrompt.current === prompt) {
      return;
    }
    if (threadState.isLoading || threadState.messages.length > 0) {
      return;
    }

    const dedupeKey = `aui:initial-prompt:${threadId}:${prompt}`;
    if (sessionStorage.getItem(dedupeKey) === "1") {
      return;
    }
    sessionStorage.setItem(dedupeKey, "1");

    threadRuntime.append(prompt);
    sentPrompt.current = prompt;
  }, [
    threadRuntime,
    threadState,
    threadId,
    initialPrompt,
    threadState?.isLoading,
    threadState?.messages.length,
  ]);

  return null;
};

export const LocalRuntimeProvider = ({
  threadId,
  initialPrompt,
}: {
  threadId: string;
  initialPrompt?: string;
}) => {
  const [isReady, setIsReady] = useState(false);
  const encodedThreadId = encodeURIComponent(threadId);

  const modelAdapter = useMemo<ChatModelAdapter>(
    () => ({
      async *run({ messages, abortSignal, runConfig, unstable_threadId }) {
        const activeThreadId = unstable_threadId ?? threadId;
        const response = await fetch(
          `${THREAD_API_BASE}/${encodeURIComponent(activeThreadId)}/runs/stream`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ messages, runConfig }),
            signal: abortSignal,
          },
        );

        if (!response.ok || !response.body) {
          throw new Error(
            (await response.text()) || "Failed to stream response",
          );
        }

        const toolCalls = new Map<string, ThreadAssistantMessagePart>();
        let textContent = "";

        for await (const event of parseBackendStream(response)) {
          if (event.type === "text_delta") {
            textContent += event.delta;
            yield { content: buildAssistantParts(textContent, toolCalls) };
            continue;
          }

          if (event.type === "tool_call") {
            toolCalls.set(event.toolCallId, {
              type: "tool-call",
              toolCallId: event.toolCallId,
              toolName: event.toolName,
              args: event.args,
              argsText: event.argsText ?? JSON.stringify(event.args),
            });
            yield { content: buildAssistantParts(textContent, toolCalls) };
            continue;
          }

          if (event.type === "tool_result") {
            const currentPart = toolCalls.get(event.toolCallId);
            if (currentPart && currentPart.type === "tool-call") {
              toolCalls.set(event.toolCallId, {
                ...currentPart,
                result: event.result,
                isError: event.isError,
              });
              yield { content: buildAssistantParts(textContent, toolCalls) };
            }
            continue;
          }

          if (event.type === "done") {
            yield {
              content: buildAssistantParts(textContent, toolCalls),
              status:
                event.status === "requires-action"
                  ? { type: "requires-action", reason: "tool-calls" }
                  : { type: "complete", reason: "stop" },
            };
            continue;
          }

          if (event.type === "error") {
            throw new Error(event.message);
          }
        }
      },
    }),
    [threadId],
  );

  const remoteThreadListAdapter = useMemo<RemoteThreadListAdapter>(
    () => ({
      async list() {
        return requestJson<{
          threads: Array<{
            status: "regular" | "archived";
            remoteId: string;
            externalId?: string;
            title?: string;
          }>;
        }>(THREAD_API_BASE);
      },
      async rename(remoteId, newTitle) {
        await requestJson(
          `${THREAD_API_BASE}/${encodeURIComponent(remoteId)}/rename`,
          {
            method: "PATCH",
            body: JSON.stringify({ title: newTitle }),
          },
        );
      },
      async archive(remoteId) {
        await requestJson(
          `${THREAD_API_BASE}/${encodeURIComponent(remoteId)}/archive`,
          {
            method: "POST",
            body: JSON.stringify({}),
          },
        );
      },
      async unarchive(remoteId) {
        await requestJson(
          `${THREAD_API_BASE}/${encodeURIComponent(remoteId)}/unarchive`,
          {
            method: "POST",
            body: JSON.stringify({}),
          },
        );
      },
      async delete(remoteId) {
        await requestJson(
          `${THREAD_API_BASE}/${encodeURIComponent(remoteId)}`,
          {
            method: "DELETE",
          },
        );
      },
      async initialize(nextThreadId) {
        return requestJson<{
          remoteId: string;
          externalId: string | undefined;
        }>(`${THREAD_API_BASE}/initialize`, {
          method: "POST",
          body: JSON.stringify({ threadId: nextThreadId }),
        });
      },
      async generateTitle() {
        return createAssistantStream(() => {});
      },
      async fetch(nextThreadId) {
        return requestJson<{
          status: "regular" | "archived";
          remoteId: string;
          externalId?: string;
          title?: string;
        }>(`${THREAD_API_BASE}/${encodeURIComponent(nextThreadId)}`);
      },
    }),
    [],
  );

  const historyAdapter = useMemo<ThreadHistoryAdapter>(
    () => ({
      async load() {
        try {
          const repository = await requestJson<HistoryRepository>(
            `${THREAD_API_BASE}/${encodedThreadId}/history`,
          );
          return normalizeHistoryRepository(repository);
        } catch {
          return { headId: null, messages: [] };
        }
      },
      async append(item) {
        await requestJson(`${THREAD_API_BASE}/${encodedThreadId}/history/append`, {
          method: "POST",
          body: JSON.stringify(item),
        });
      },
    }),
    [encodedThreadId],
  );

  const runtime = useRemoteThreadListRuntime({
    runtimeHook: () =>
      useLocalRuntime(modelAdapter, {
        adapters: { history: historyAdapter },
        unstable_humanToolNames: HUMAN_TOOL_NAMES,
      }),
    adapter: remoteThreadListAdapter,
  });

  useEffect(() => {
    let cancelled = false;

    const setup = async () => {
      setIsReady(false);
      try {
        await requestJson(
          `${THREAD_API_BASE}/${encodeURIComponent(threadId)}`,
          { method: "GET" },
        );
      } catch {
        await requestJson(`${THREAD_API_BASE}/initialize`, {
          method: "POST",
          body: JSON.stringify({ threadId }),
        });
      }

      await runtime.threads.switchToThread(threadId);
      if (!cancelled) {
        setIsReady(true);
      }
    };

    void setup();

    return () => {
      cancelled = true;
    };
  }, [runtime, threadId]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="h-dvh">
        {isReady ? (
          <>
            <InitialPromptSender
              threadId={threadId}
              initialPrompt={initialPrompt}
            />
            <Thread />
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
            Loading thread...
          </div>
        )}
      </div>
    </AssistantRuntimeProvider>
  );
};
