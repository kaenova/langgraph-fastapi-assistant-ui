"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FC } from "react";
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";

import { Thread } from "@/components/assistant-ui/thread";
import {
  WELCOME_INITIAL_MESSAGE_KEY_PREFIX,
  createAttachmentAdapter,
  fetchThreadMessages,
  streamThreadRun,
  toBackendMessageInput,
  type BackendRunRequest,
} from "@/lib/external-store-chat";

type ChatThreadPageProps = {
  threadId: string;
};

const applyTokenToMessages = (
  currentMessages: ThreadMessageLike[],
  token: {
    targetMessageId: string;
    text: string;
    replaceFromMessageId?: string | null;
  },
): ThreadMessageLike[] => {
  if (!token.text || !token.targetMessageId) return currentMessages;

  const nextMessages = [...currentMessages];
  let messageIndex = nextMessages.findIndex((m) => m.id === token.targetMessageId);
  if (messageIndex === -1 && token.replaceFromMessageId) {
    messageIndex = nextMessages.findIndex(
      (m) => m.id === token.replaceFromMessageId,
    );
  }

  if (messageIndex === -1) {
    nextMessages.push({
      id: token.targetMessageId,
      role: "assistant",
      content: [{ type: "text", text: token.text }],
      metadata: { custom: {} },
      status: { type: "running" },
    });
    return nextMessages;
  }

  const assistantMessage = nextMessages[messageIndex];
  if (!assistantMessage || assistantMessage.role !== "assistant") {
    return nextMessages;
  }

  const contentArray = Array.isArray(assistantMessage.content)
    ? [...assistantMessage.content]
    : [{ type: "text" as const, text: assistantMessage.content }];

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

export const ChatThreadPage: FC<ChatThreadPageProps> = ({ threadId }) => {
  const [messages, setMessages] = useState<ThreadMessageLike[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const processedInitialPayloadRef = useRef(false);
  const tokenTargetMessageIdRef = useRef<string | null>(null);
  const attachmentAdapter = useMemo(createAttachmentAdapter, []);

  const runStream = useCallback(
    async (payload: BackendRunRequest) => {
      abortControllerRef.current?.abort();
      const controller = new AbortController();
      abortControllerRef.current = controller;
      tokenTargetMessageIdRef.current = null;

      setError(null);
      setIsRunning(true);
      try {
        await streamThreadRun({
          threadId,
          payload,
          signal: controller.signal,
          onSnapshot: (nextMessages) => setMessages([...nextMessages]),
          onToken: (token) => {
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
        setError(
          streamError instanceof Error
            ? streamError.message
            : "Failed to stream response",
        );
      } finally {
        tokenTargetMessageIdRef.current = null;
        setIsRunning(false);
      }
    },
    [threadId],
  );

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

  useEffect(() => {
    let active = true;

    const initialize = async () => {
      try {
        const existingMessages = await fetchThreadMessages(threadId);
        if (active) {
          setMessages(existingMessages);
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

      const key = `${WELCOME_INITIAL_MESSAGE_KEY_PREFIX}${threadId}`;
      const rawPayload = sessionStorage.getItem(key);
      if (!rawPayload) return;

      sessionStorage.removeItem(key);
      try {
        const payload = JSON.parse(rawPayload) as BackendRunRequest["message"];
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

  const runtime = useExternalStoreRuntime<ThreadMessageLike>({
    isRunning,
    messages,
    setMessages: (nextMessages) => setMessages([...nextMessages]),
    convertMessage: (message) => message,
    onNew,
    onEdit,
    onReload,
    onCancel: async () => {
      abortControllerRef.current?.abort();
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
