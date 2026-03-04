"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AssistantRuntimeProvider,
  unstable_useRemoteThreadListRuntime as useRemoteThreadListRuntime,
  useThread,
  useThreadRuntime,
} from "@assistant-ui/react";

import { Thread } from "@/components/assistant-ui/thread";
import { WELCOME_INITIAL_MESSAGE_KEY_PREFIX } from "@/lib/assistant-template/constants";
import type { WelcomeInitialMessagePayload } from "@/lib/assistant-template/types";

import {
  createHistoryAdapter,
  createModelAdapter,
  createRemoteThreadListAdapter,
} from "./adapters";
import {
  hasNextShouldCompactFlag,
  sliceMessagesFromLatestCompaction,
  toAssistantCustomMetadata,
} from "./compaction-utils";
import {
  COMPACTION_API_BASE,
  requestJson,
  THREAD_API_BASE,
} from "./thread-api";
import { useTemplateLocalRuntime } from "./use-template-local-runtime";

// Appends the welcome-page message once after empty thread history is loaded.
const InitialWelcomeMessageSender = ({ threadId }: { threadId: string }) => {
  const threadRuntime = useThreadRuntime({ optional: true });
  const threadState = useThread({ optional: true });
  const hasSent = useRef(false);

  useEffect(() => {
    if (!threadRuntime || !threadState || hasSent.current) {
      return;
    }
    if (threadState.isLoading || threadState.messages.length > 0) {
      return;
    }

    const storageKey = `${WELCOME_INITIAL_MESSAGE_KEY_PREFIX}${threadId}`;
    const payloadRaw = sessionStorage.getItem(storageKey);
    if (!payloadRaw) {
      return;
    }

    try {
      const payload = JSON.parse(payloadRaw) as WelcomeInitialMessagePayload;
      if (!Array.isArray(payload.content) || payload.content.length === 0) {
        sessionStorage.removeItem(storageKey);
        return;
      }
      threadRuntime.append({
        role: "user",
        content: payload.content,
        attachments: Array.isArray(payload.attachments)
          ? payload.attachments
          : [],
      });
      sessionStorage.removeItem(storageKey);
      hasSent.current = true;
    } catch {
      sessionStorage.removeItem(storageKey);
    }
  }, [
    threadRuntime,
    threadState,
    threadId,
    threadState?.isLoading,
    threadState?.messages.length,
  ]);

  return null;
};

type CompactResponse = {
  message: {
    role?: string;
    content?: unknown;
    metadata?: unknown;
    createdAt?: string;
  };
};

// Auto-runs compaction when backend marks the latest assistant message.
const ThreadCompactionSync = () => {
  const threadRuntime = useThreadRuntime({ optional: true });
  const threadState = useThread({ optional: true });
  const isCompactingRef = useRef(false);
  const attemptedFlagMessageIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!threadRuntime || !threadState) {
      return;
    }
    if (threadState.isLoading || threadState.isRunning) {
      return;
    }
    if (threadState.messages.length === 0 || isCompactingRef.current) {
      return;
    }

    const lastMessage = threadState.messages[threadState.messages.length - 1];
    if (!hasNextShouldCompactFlag(lastMessage)) {
      return;
    }

    const lastMessageId =
      lastMessage && typeof lastMessage.id === "string" ? lastMessage.id : null;
    if (!lastMessageId) {
      return;
    }
    if (attemptedFlagMessageIdRef.current === lastMessageId) {
      return;
    }

    attemptedFlagMessageIdRef.current = lastMessageId;
    isCompactingRef.current = true;

    const compactContextMessages = sliceMessagesFromLatestCompaction(
      threadState.messages,
    );

    const runCompaction = async () => {
      try {
        const response = await requestJson<CompactResponse>(COMPACTION_API_BASE, {
          method: "POST",
          body: JSON.stringify({ messages: compactContextMessages }),
        });

        const compactedMessage = response.message;
        if (compactedMessage?.role !== "assistant") {
          return;
        }

        const messageContent = Array.isArray(compactedMessage.content)
          ? compactedMessage.content
          : [];
        const metadata = toAssistantCustomMetadata(compactedMessage.metadata);

        threadRuntime.append({
          role: "assistant",
          content: messageContent,
          metadata,
          createdAt: compactedMessage.createdAt
            ? new Date(compactedMessage.createdAt)
            : undefined,
        });
      } catch {
        // noop
      } finally {
        isCompactingRef.current = false;
      }
    };

    void runCompaction();
  }, [threadRuntime, threadState]);

  return null;
};

// Wires assistant runtime, thread list, and history adapters for a chat thread.
export const LocalRuntimeProvider = ({ threadId }: { threadId: string }) => {
  const [isReady, setIsReady] = useState(false);
  const encodedThreadId = encodeURIComponent(threadId);

  const modelAdapter = useMemo(() => createModelAdapter(threadId), [threadId]);
  const remoteThreadListAdapter = useMemo(
    () => createRemoteThreadListAdapter(),
    [],
  );
  const historyAdapter = useMemo(
    () => createHistoryAdapter(encodedThreadId),
    [encodedThreadId],
  );

  const runtime = useRemoteThreadListRuntime({
    runtimeHook: () =>
      useTemplateLocalRuntime({
        modelAdapter,
        historyAdapter,
      }),
    adapter: remoteThreadListAdapter,
  });

  useEffect(() => {
    let cancelled = false;

    // Ensures the thread is selected before rendering the chat UI.
    const setup = async () => {
      setIsReady(false);
      try {
        await requestJson(
          `${THREAD_API_BASE}/${encodeURIComponent(threadId)}`,
          {
            method: "GET",
          },
        );
      } catch {
        // noop
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
      <div className="h-full">
        {isReady ? (
          <>
            <InitialWelcomeMessageSender threadId={threadId} />
            <ThreadCompactionSync />
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
