"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FC } from "react";
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type AppendMessage,
  type ExportedMessageRepository,
  type ThreadMessage,
} from "@assistant-ui/react";

import { Thread } from "@/components/assistant-ui/thread";
import {
  WELCOME_INITIAL_MESSAGE_KEY_PREFIX,
  createAttachmentAdapter,
  fetchThreadMessages,
  streamThreadRun,
  toBackendMessageInput,
  type BackendRunRequest,
} from "./external-store-chat";

type ChatThreadPageProps = {
  threadId: string;
};

// Creates a temporary running assistant message used while token chunks are streaming.
const createRunningAssistantMessage = (
  messageId: string,
  text: string,
): ThreadMessage => {
  return {
    id: messageId,
    role: "assistant",
    createdAt: new Date(),
    content: [{ type: "text", text }],
    status: { type: "running" },
    metadata: {
      unstable_state: null,
      unstable_annotations: [],
      unstable_data: [],
      steps: [],
      custom: {},
    },
  };
};

// Applies an incremental token to the linear message list during active streaming.
const applyTokenToMessages = (
  messages: ThreadMessage[],
  token: {
    targetMessageId: string;
    text: string;
    replaceFromMessageId?: string | null;
  },
) => {
  if (!token.text || !token.targetMessageId) return messages;

  const nextMessages = [...messages];
  let messageIndex = nextMessages.findIndex(
    (message) => message.id === token.targetMessageId,
  );
  if (messageIndex === -1 && token.replaceFromMessageId) {
    messageIndex = nextMessages.findIndex(
      (message) => message.id === token.replaceFromMessageId,
    );
  }

  if (messageIndex === -1) {
    nextMessages.push(createRunningAssistantMessage(token.targetMessageId, token.text));
    return nextMessages;
  }

  const assistantMessage = nextMessages[messageIndex];
  if (!assistantMessage || assistantMessage.role !== "assistant") {
    return nextMessages;
  }
  const contentArray = [...assistantMessage.content];

  const lastPart = contentArray[contentArray.length - 1];
  if (lastPart?.type === "text") {
    contentArray[contentArray.length - 1] = {
      ...lastPart,
      text: `${lastPart.text}${token.text}`,
    };
  } else {
    contentArray.push({ type: "text", text: token.text });
  }

  nextMessages[messageIndex] = {
    ...assistantMessage,
    id: token.targetMessageId,
    content: contentArray,
    status: { type: "running" },
  };

  return nextMessages;
};

// Hosts the chat-thread runtime that syncs state with LangGraph-backed external store endpoints.
export const ChatThreadPage: FC<ChatThreadPageProps> = ({ threadId }) => {
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [messageRepository, setMessageRepository] =
    useState<ExportedMessageRepository>();
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const processedInitialPayloadRef = useRef(false);
  const tokenTargetMessageIdRef = useRef<string | null>(null);
  const activeStreamSessionIdRef = useRef<string | null>(null);
  const activeBackendRunIdRef = useRef<string | null>(null);
  const lastBackendSequenceRef = useRef(0);
  const attachmentAdapter = useMemo(createAttachmentAdapter, []);

  // Starts a backend run stream and reconciles token/snapshot events into runtime state.
  const runStream = useCallback(
    async (payload: BackendRunRequest) => {
      abortControllerRef.current?.abort();
      const controller = new AbortController();
      const streamSessionId = crypto.randomUUID();
      abortControllerRef.current = controller;
      activeStreamSessionIdRef.current = streamSessionId;
      activeBackendRunIdRef.current = null;
      lastBackendSequenceRef.current = 0;
      tokenTargetMessageIdRef.current = null;

      setError(null);
      setIsRunning(true);
      try {
        await streamThreadRun({
          threadId,
          payload,
          signal: controller.signal,
          onSnapshot: (snapshot) => {
            if (activeStreamSessionIdRef.current !== streamSessionId) return;
            if (snapshot.runId) {
              if (
                activeBackendRunIdRef.current &&
                activeBackendRunIdRef.current !== snapshot.runId
              ) {
                return;
              }
              activeBackendRunIdRef.current = snapshot.runId;
            }
            if (snapshot.sequence != null) {
              if (snapshot.sequence <= lastBackendSequenceRef.current) return;
              lastBackendSequenceRef.current = snapshot.sequence;
            }
            setMessages([...snapshot.messages]);
            if (snapshot.messageRepository) {
              setMessageRepository(snapshot.messageRepository);
            }
          },
          onToken: (token) => {
            if (activeStreamSessionIdRef.current !== streamSessionId) return;
            if (token.runId) {
              if (
                activeBackendRunIdRef.current &&
                activeBackendRunIdRef.current !== token.runId
              ) {
                return;
              }
              activeBackendRunIdRef.current = token.runId;
            }
            if (token.sequence != null) {
              if (token.sequence <= lastBackendSequenceRef.current) return;
              lastBackendSequenceRef.current = token.sequence;
            }

            let targetMessageId = token.messageId;
            let replaceFromMessageId: string | null = null;

            if (!targetMessageId) {
              if (!tokenTargetMessageIdRef.current) {
                tokenTargetMessageIdRef.current = `pending-${crypto.randomUUID()}`;
              }
              targetMessageId = tokenTargetMessageIdRef.current;
            } else {
              if (
                tokenTargetMessageIdRef.current &&
                tokenTargetMessageIdRef.current !== targetMessageId
              ) {
                replaceFromMessageId = tokenTargetMessageIdRef.current;
              }
              tokenTargetMessageIdRef.current = targetMessageId;
            }

            if (!targetMessageId) return;
            setMessages((currentMessages) =>
              applyTokenToMessages(currentMessages, {
                targetMessageId,
                text: token.text,
                replaceFromMessageId,
              }),
            );
          },
        });
      } catch (streamError) {
        if (
          streamError instanceof DOMException &&
          streamError.name === "AbortError"
        ) {
          return;
        }
        if (activeStreamSessionIdRef.current !== streamSessionId) return;
        setError(
          streamError instanceof Error
            ? streamError.message
            : "Failed to stream response",
        );
      } finally {
        if (activeStreamSessionIdRef.current === streamSessionId) {
          activeStreamSessionIdRef.current = null;
          activeBackendRunIdRef.current = null;
          lastBackendSequenceRef.current = 0;
          tokenTargetMessageIdRef.current = null;
          setIsRunning(false);
        }
      }
    },
    [threadId],
  );

  // Sends a new user message through backend-authoritative run flow.
  const onNew = useCallback(
    async (message: AppendMessage) => {
      await runStream({
        parent_message_id: message.parentId,
        source_message_id: message.sourceId,
        run_config: message.runConfig ?? undefined,
        message: toBackendMessageInput(message),
      });
    },
    [runStream],
  );

  // Submits an edited message using source_message_id for checkpoint-based user branching.
  const onEdit = useCallback(
    async (message: AppendMessage) => {
      await runStream({
        parent_message_id: message.parentId,
        source_message_id: message.sourceId,
        run_config: message.runConfig ?? undefined,
        message: toBackendMessageInput(message),
      });
    },
    [runStream],
  );

  // Triggers regenerate from a selected parent branch without appending a new user message.
  const onReload = useCallback(
    async (
      parentId: string | null,
      config: { runConfig: Record<string, unknown> },
    ) => {
      await runStream({
        parent_message_id: parentId,
        run_config: config.runConfig ?? undefined,
      });
    },
    [runStream],
  );

  // Initializes thread state from backend and optionally consumes welcome handoff payload.
  useEffect(() => {
    let active = true;

    const initialize = async () => {
      const key = `${WELCOME_INITIAL_MESSAGE_KEY_PREFIX}${threadId}`;
      const rawPayload = sessionStorage.getItem(key);
      if (rawPayload && !processedInitialPayloadRef.current && active) {
        processedInitialPayloadRef.current = true;
        sessionStorage.removeItem(key);
        try {
          const payload = JSON.parse(rawPayload) as BackendRunRequest["message"];
          if (!payload) return;
          await runStream({ message: payload });
          return;
        } catch (payloadError) {
          setError(
            payloadError instanceof Error
              ? payloadError.message
              : "Failed to start welcome message",
          );
        }
      }

      try {
        const existingThread = await fetchThreadMessages(threadId);
        if (active) {
          setMessages(existingThread.messages);
          if (existingThread.messageRepository) {
            setMessageRepository(existingThread.messageRepository);
          }
        }
      } catch (initialLoadError) {
        if (!active) return;
        setError(
          initialLoadError instanceof Error
            ? initialLoadError.message
            : "Failed to load thread",
        );
      }

      if (processedInitialPayloadRef.current || !active) {
        return;
      }
      processedInitialPayloadRef.current = true;

      const deferredRawPayload = sessionStorage.getItem(key);
      if (!deferredRawPayload) return;

      sessionStorage.removeItem(key);
      try {
        const payload = JSON.parse(deferredRawPayload) as BackendRunRequest["message"];
        if (!payload) return;
        await runStream({ message: payload });
      } catch (payloadError) {
        setError(
          payloadError instanceof Error
            ? payloadError.message
            : "Failed to start welcome message",
        );
      }
    };

    void initialize();
    return () => {
      active = false;
    };
  }, [runStream, threadId]);

  const runtime = useExternalStoreRuntime<ThreadMessage>({
    isRunning,
    messages,
    messageRepository: isRunning ? undefined : messageRepository,
    setMessages: (nextMessages) => {
      const next = [...nextMessages];
      setMessages(next);
      setMessageRepository((current) => {
        if (!current) return current;
        const nextHeadId = next.at(-1)?.id ?? null;
        if (current.headId === nextHeadId) return current;
        return { ...current, headId: nextHeadId };
      });
    },
    onNew,
    onEdit,
    onReload,
    onCancel: async () => {
      abortControllerRef.current?.abort();
      activeStreamSessionIdRef.current = null;
      activeBackendRunIdRef.current = null;
      lastBackendSequenceRef.current = 0;
      tokenTargetMessageIdRef.current = null;
      setIsRunning(false);
    },
    adapters: {
      attachments: attachmentAdapter,
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="h-dvh">
        <Thread />
      </div>
      {error ? (
        <div className="fixed right-4 bottom-4 rounded-md border border-destructive bg-destructive/10 px-3 py-2 text-destructive text-sm">
          {error}
        </div>
      ) : null}
    </AssistantRuntimeProvider>
  );
};
