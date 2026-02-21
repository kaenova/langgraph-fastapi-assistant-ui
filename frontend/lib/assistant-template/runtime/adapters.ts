import {
  type ChatModelAdapter,
  type ThreadAssistantMessagePart,
  type ThreadHistoryAdapter,
  type unstable_RemoteThreadListAdapter as RemoteThreadListAdapter,
} from "@assistant-ui/react";
import { createAssistantStream } from "assistant-stream";

import { parseBackendStream } from "./backend-stream";
import { normalizeHistoryRepository } from "./history-repository";
import { requestJson, THREAD_API_BASE } from "./thread-api";
import type { HistoryRepository } from "./types";

// Builds the streaming chat adapter that maps backend events into assistant-ui parts.
export function createModelAdapter(threadId: string): ChatModelAdapter {
  return {
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
        throw new Error((await response.text()) || "Failed to stream response");
      }

      const orderedParts: ThreadAssistantMessagePart[] = [];
      const toolPartIndexes = new Map<string, number>();

      // Emits immutable snapshots so runtime updates render progressively.
      const snapshotParts = () =>
        orderedParts.map((part) =>
          part.type === "tool-call" ? { ...part } : { ...part },
        );

      // Coalesces contiguous text chunks from streamed text_delta events.
      const appendTextDelta = (delta: string) => {
        if (!delta) return;
        const lastIndex = orderedParts.length - 1;
        const lastPart = lastIndex >= 0 ? orderedParts[lastIndex] : undefined;
        if (lastPart && lastPart.type === "text") {
          orderedParts[lastIndex] = {
            ...lastPart,
            text: `${lastPart.text}${delta}`,
          };
          return;
        }
        orderedParts.push({ type: "text", text: delta });
      };

      for await (const event of parseBackendStream(response)) {
        if (event.type === "text_delta") {
          appendTextDelta(event.delta);
          yield { content: snapshotParts() };
          continue;
        }

        if (event.type === "tool_call") {
          const nextPart: ThreadAssistantMessagePart = {
            type: "tool-call",
            toolCallId: event.toolCallId,
            toolName: event.toolName,
            args: event.args,
            argsText: event.argsText ?? JSON.stringify(event.args),
          };
          const existingIndex = toolPartIndexes.get(event.toolCallId);
          if (existingIndex === undefined) {
            toolPartIndexes.set(event.toolCallId, orderedParts.length);
            orderedParts.push(nextPart);
          } else {
            const previousPart = orderedParts[existingIndex];
            orderedParts[existingIndex] =
              previousPart?.type === "tool-call"
                ? { ...previousPart, ...nextPart }
                : nextPart;
          }
          yield { content: snapshotParts() };
          continue;
        }

        if (event.type === "tool_result") {
          const existingIndex = toolPartIndexes.get(event.toolCallId);
          if (existingIndex !== undefined) {
            const currentPart = orderedParts[existingIndex];
            if (currentPart?.type === "tool-call") {
              orderedParts[existingIndex] = {
                ...currentPart,
                result: event.result,
                isError: event.isError,
              };
              yield { content: snapshotParts() };
            }
          } else {
            toolPartIndexes.set(event.toolCallId, orderedParts.length);
            orderedParts.push({
              type: "tool-call",
              toolCallId: event.toolCallId,
              toolName: "tool",
              args: {},
              argsText: "{}",
              result: event.result,
              isError: event.isError,
            });
            yield { content: snapshotParts() };
          }
          continue;
        }

        if (event.type === "done") {
          yield {
            content: snapshotParts(),
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
  };
}

// Creates the remote thread-list adapter for list, lifecycle, and metadata APIs.
export function createRemoteThreadListAdapter(): RemoteThreadListAdapter {
  return {
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
      await requestJson(`${THREAD_API_BASE}/${encodeURIComponent(remoteId)}/rename`, {
        method: "PATCH",
        body: JSON.stringify({ title: newTitle }),
      });
    },
    async archive(remoteId) {
      await requestJson(`${THREAD_API_BASE}/${encodeURIComponent(remoteId)}/archive`, {
        method: "POST",
        body: JSON.stringify({}),
      });
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
      await requestJson(`${THREAD_API_BASE}/${encodeURIComponent(remoteId)}`, {
        method: "DELETE",
      });
    },
    async initialize(nextThreadId) {
      if (nextThreadId.startsWith("__LOCALID_")) {
        return {
          remoteId: nextThreadId,
          externalId: undefined,
        };
      }

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
  };
}

// Creates history load/append hooks used by LocalRuntime branching persistence.
export function createHistoryAdapter(
  encodedThreadId: string,
): ThreadHistoryAdapter {
  return {
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
  };
}
