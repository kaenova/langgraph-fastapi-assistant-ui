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
} from "@/lib/external-store-chat";

type ChatThreadPageProps = {
  threadId: string;
};

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

const applyTokenToRepository = (
  repository: ExportedMessageRepository | undefined,
  token: {
    targetMessageId: string;
    text: string;
    replaceFromMessageId?: string | null;
  },
) => {
  if (!token.text || !token.targetMessageId) return repository;

  const currentRepository: ExportedMessageRepository = repository ?? {
    headId: null,
    messages: [],
  };
  const nextRepository: ExportedMessageRepository = {
    headId: currentRepository.headId ?? null,
    messages: currentRepository.messages.map((item) => ({ ...item })),
  };

  let messageIndex = nextRepository.messages.findIndex(
    (item) => item.message.id === token.targetMessageId,
  );
  if (messageIndex === -1 && token.replaceFromMessageId) {
    messageIndex = nextRepository.messages.findIndex(
      (item) => item.message.id === token.replaceFromMessageId,
    );
  }

  if (messageIndex === -1) {
    nextRepository.messages.push({
      parentId: nextRepository.headId ?? null,
      message: createRunningAssistantMessage(token.targetMessageId, token.text),
    });
    nextRepository.headId = token.targetMessageId;
    return nextRepository;
  }

  const messageItem = nextRepository.messages[messageIndex];
  if (!messageItem || messageItem.message.role !== "assistant") {
    return nextRepository;
  }

  const assistantMessage = messageItem.message;
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

  const replacedFromMessageId = token.replaceFromMessageId;
  nextRepository.messages[messageIndex] = {
    ...messageItem,
    message: {
      ...assistantMessage,
      id: token.targetMessageId,
      content: contentArray,
      status: { type: "running" },
    },
  };

  if (replacedFromMessageId && replacedFromMessageId !== token.targetMessageId) {
    for (const item of nextRepository.messages) {
      if (item.parentId === replacedFromMessageId) {
        item.parentId = token.targetMessageId;
      }
    }
    if (nextRepository.headId === replacedFromMessageId) {
      nextRepository.headId = token.targetMessageId;
    }
  }

  nextRepository.headId = token.targetMessageId;
  return nextRepository;
};

export const ChatThreadPage: FC<ChatThreadPageProps> = ({ threadId }) => {
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [messageRepository, setMessageRepository] =
    useState<ExportedMessageRepository>();
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
          onSnapshot: (snapshot) => {
            setMessages([...snapshot.messages]);
            if (snapshot.messageRepository) {
              setMessageRepository(snapshot.messageRepository);
            }
          },
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
            setMessageRepository((currentRepository) =>
              applyTokenToRepository(currentRepository, {
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

  const runtime = useExternalStoreRuntime<ThreadMessage>({
    isRunning,
    messages,
    messageRepository,
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
