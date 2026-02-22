"use client";

import {
  CompositeAttachmentAdapter,
  SimpleImageAttachmentAdapter,
  SimpleTextAttachmentAdapter,
  type AppendMessage,
  type ExportedMessageRepository,
  type ThreadMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { MessageRepository, fromThreadMessageLike } from "@assistant-ui/core/internal";

export const WELCOME_INITIAL_MESSAGE_KEY_PREFIX = "welcome-initial-message:";

export type BackendMessageInput = {
  content: AppendMessage["content"];
  attachments: AppendMessage["attachments"];
};

export type BackendRunRequest = {
  message?: BackendMessageInput;
  parent_message_id?: string | null;
  source_message_id?: string | null;
  run_config?: Record<string, unknown>;
};

export type BackendMessageRepository = {
  headId?: string | null;
  messages: Array<{
    parentId: string | null;
    message: ThreadMessageLike;
  }>;
};

type BackendSnapshotEvent = {
  type: "snapshot";
  messages: ThreadMessageLike[];
  messageRepository?: BackendMessageRepository;
};

type BackendTokenEvent = {
  type: "token";
  message_id?: string | null;
  text: string;
};

type BackendErrorEvent = {
  type: "error";
  error: string;
};

type BackendEvent = BackendSnapshotEvent | BackendTokenEvent | BackendErrorEvent;

export const toBackendMessageInput = (
  message: AppendMessage,
): BackendMessageInput => ({
  content: [...message.content],
  attachments: [...(message.attachments ?? [])],
});

export const createAttachmentAdapter = () => {
  return new CompositeAttachmentAdapter([
    new SimpleImageAttachmentAdapter(),
    new SimpleTextAttachmentAdapter(),
  ]);
};

export const fetchThreadMessages = async (
  threadId: string,
): Promise<{
  messages: ThreadMessage[];
  messageRepository?: ExportedMessageRepository;
}> => {
  const response = await fetch(`/api/be/api/v1/threads/${encodeURIComponent(threadId)}/messages`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const payload = (await response.json()) as {
    messages?: ThreadMessageLike[];
    messageRepository?: BackendMessageRepository;
  };
  return {
    messages: (payload.messages ?? []).map((message, index) =>
      fromThreadMessageLike(
        message,
        message.id ?? `snapshot-${index}-${crypto.randomUUID()}`,
        { type: "complete", reason: "unknown" },
      ),
    ),
    messageRepository: toExportedMessageRepository(payload.messageRepository),
  };
};

export const toExportedMessageRepository = (
  repository?: BackendMessageRepository,
): ExportedMessageRepository | undefined => {
  if (!repository) return undefined;

  const messageRepository = new MessageRepository();
  const messageIds = new Set<string>();
  let lastMessageId: string | null = null;
  for (const item of repository.messages) {
    const fallbackId = item.message.id ?? crypto.randomUUID();
    const convertedMessage = fromThreadMessageLike(item.message, fallbackId, {
      type: "complete",
      reason: "unknown",
    });
    messageRepository.addOrUpdateMessage(item.parentId, convertedMessage);
    messageIds.add(convertedMessage.id);
    lastMessageId = convertedMessage.id;
  }

  const requestedHeadId = repository.headId ?? null;
  const safeHeadId =
    requestedHeadId && messageIds.has(requestedHeadId)
      ? requestedHeadId
      : lastMessageId;

  messageRepository.resetHead(
    safeHeadId,
  );
  return messageRepository.export();
};

export const streamThreadRun = async ({
  threadId,
  payload,
  signal,
  onSnapshot,
  onToken,
}: {
  threadId: string;
  payload: BackendRunRequest;
  signal?: AbortSignal;
  onSnapshot: (snapshot: {
    messages: ThreadMessage[];
    messageRepository?: ExportedMessageRepository;
  }) => void;
  onToken?: (token: { messageId: string | null; text: string }) => void;
}): Promise<void> => {
  const response = await fetch(
    `/api/be/api/v1/threads/${encodeURIComponent(threadId)}/runs/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    },
  );

  if (!response.ok || !response.body) {
    throw new Error(await response.text());
  }

  const reader = response.body.getReader();
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
      const event = JSON.parse(trimmed) as BackendEvent;
      if (event.type === "error") {
        throw new Error(event.error);
      }
      if (event.type === "token") {
        onToken?.({
          messageId: event.message_id ?? null,
          text: event.text,
        });
        continue;
      }
      onSnapshot({
        messages: (event.messages ?? []).map((message, index) =>
          fromThreadMessageLike(
            message,
            message.id ?? `stream-${index}-${crypto.randomUUID()}`,
            { type: "complete", reason: "unknown" },
          ),
        ),
        messageRepository: toExportedMessageRepository(event.messageRepository),
      });
    }
  }
};
