"use client";

import {
  CompositeAttachmentAdapter,
  SimpleImageAttachmentAdapter,
  SimpleTextAttachmentAdapter,
  type AppendMessage,
  type CompleteAttachment,
  type ExportedMessageRepository,
  type ThreadUserMessagePart,
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

const inferImageContentType = (value: string): string => {
  if (!value.startsWith("data:")) return "image/*";
  const metadata = value.slice(5).split(",", 1)[0] ?? "";
  const contentType = metadata.split(";", 1)[0] ?? "";
  return contentType || "image/*";
};

const toAttachmentFromUserPart = (
  messageId: string,
  index: number,
  part: ThreadUserMessagePart,
): CompleteAttachment | null => {
  const id = `${messageId}-content-${index}`;
  if (part.type === "image") {
    return {
      id,
      type: "image",
      name: part.filename ?? `image-${index + 1}`,
      contentType: inferImageContentType(part.image),
      status: { type: "complete" },
      content: [part],
    };
  }

  if (part.type === "file") {
    return {
      id,
      type: part.mimeType.startsWith("text/") ? "document" : "file",
      name: part.filename ?? `file-${index + 1}`,
      contentType: part.mimeType,
      status: { type: "complete" },
      content: [part],
    };
  }

  if (part.type === "data") {
    return {
      id,
      type: "file",
      name: `${part.name}.json`,
      contentType: "application/json",
      status: { type: "complete" },
      content: [part],
    };
  }

  if (part.type === "audio") {
    return {
      id,
      type: "file",
      name: `audio-${index + 1}.${part.audio.format}`,
      contentType: `audio/${part.audio.format}`,
      status: { type: "complete" },
      content: [part],
    };
  }

  return null;
};

const normalizeUserMessageLike = (
  message: ThreadMessageLike,
  fallbackId: string,
): ThreadMessageLike => {
  if (message.role !== "user" || !Array.isArray(message.content)) return message;

  const textParts: ThreadUserMessagePart[] = [];
  const derivedAttachments: CompleteAttachment[] = [];

  for (const [index, part] of message.content.entries()) {
    const attachment = toAttachmentFromUserPart(
      message.id ?? fallbackId,
      index,
      part as ThreadUserMessagePart,
    );
    if (attachment) {
      derivedAttachments.push(attachment);
      continue;
    }
    if ((part as ThreadUserMessagePart).type === "text") {
      textParts.push(part as ThreadUserMessagePart);
    }
  }

  if (derivedAttachments.length === 0) return message;

  const existingAttachments = [...(message.attachments ?? [])];
  const seenIds = new Set(existingAttachments.map((attachment) => attachment.id));
  for (const attachment of derivedAttachments) {
    if (seenIds.has(attachment.id)) continue;
    seenIds.add(attachment.id);
    existingAttachments.push(attachment);
  }

  return {
    ...message,
    content: textParts.length > 0 ? textParts : [{ type: "text", text: "" }],
    attachments: existingAttachments,
  };
};

const toThreadMessage = (message: ThreadMessageLike, fallbackId: string): ThreadMessage =>
  fromThreadMessageLike(
    normalizeUserMessageLike(message, fallbackId),
    fallbackId,
    { type: "complete", reason: "unknown" },
  );

const mergeToolResultsIntoRepository = (
  repository: BackendMessageRepository | undefined,
  messages: ThreadMessageLike[],
): BackendMessageRepository | undefined => {
  if (!repository) return undefined;

  const byMessageAndToolId = new Map<string, { result?: unknown; isError?: boolean }>();
  const byToolId = new Map<string, { result?: unknown; isError?: boolean }>();

  for (const message of messages) {
    if (!Array.isArray(message.content)) continue;
    for (const part of message.content) {
      if (!part || typeof part !== "object" || part.type !== "tool-call") continue;
      const toolCallId = "toolCallId" in part ? part.toolCallId : undefined;
      if (!toolCallId) continue;
      const payload = {
        result: "result" in part ? part.result : undefined,
        isError: "isError" in part ? part.isError : undefined,
      };
      if (payload.result === undefined && payload.isError === undefined) continue;
      if (message.id) {
        byMessageAndToolId.set(`${message.id}:${toolCallId}`, payload);
      }
      byToolId.set(toolCallId, payload);
    }
  }

  if (byMessageAndToolId.size === 0 && byToolId.size === 0) return repository;

  return {
    ...repository,
    messages: repository.messages.map((item) => {
      const content = item.message.content;
      if (!Array.isArray(content)) return item;
      let changed = false;
      const mergedContent = content.map((part) => {
        if (!part || typeof part !== "object" || part.type !== "tool-call") {
          return part;
        }
        const toolCallId = "toolCallId" in part ? part.toolCallId : undefined;
        if (!toolCallId || "result" in part) return part;
        const source =
          byMessageAndToolId.get(`${item.message.id ?? ""}:${toolCallId}`) ??
          byToolId.get(toolCallId);
        if (!source || source.result === undefined) return part;
        changed = true;
        return {
          ...part,
          result: source.result,
          ...(source.isError ? { isError: source.isError } : {}),
        };
      });
      if (!changed) return item;
      return {
        ...item,
        message: {
          ...item.message,
          content: mergedContent,
        },
      };
    }),
  };
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
  const normalizedMessages = payload.messages ?? [];
  return {
    messages: normalizedMessages.map((message, index) => {
      const fallbackId = message.id ?? `snapshot-${index}-${crypto.randomUUID()}`;
      return toThreadMessage(message, fallbackId);
    }),
    messageRepository: toExportedMessageRepository(
      mergeToolResultsIntoRepository(payload.messageRepository, normalizedMessages),
    ),
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
    const convertedMessage = toThreadMessage(item.message, fallbackId);
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
        messages: (event.messages ?? []).map((message, index) => {
          const fallbackId = message.id ?? `stream-${index}-${crypto.randomUUID()}`;
          return toThreadMessage(message, fallbackId);
        }),
        messageRepository: toExportedMessageRepository(
          mergeToolResultsIntoRepository(event.messageRepository, event.messages ?? []),
        ),
      });
    }
  }
};
