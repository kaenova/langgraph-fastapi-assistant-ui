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
import { requestJson, THREAD_API_BASE } from "./thread-api";
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
