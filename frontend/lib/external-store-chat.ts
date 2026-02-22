"use client";

import {
  CompositeAttachmentAdapter,
  SimpleImageAttachmentAdapter,
  SimpleTextAttachmentAdapter,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";

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

type BackendSnapshotEvent = {
  type: "snapshot";
  messages: ThreadMessageLike[];
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
): Promise<ThreadMessageLike[]> => {
  const response = await fetch(`/api/be/api/v1/threads/${encodeURIComponent(threadId)}/messages`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const payload = (await response.json()) as { messages?: ThreadMessageLike[] };
  return payload.messages ?? [];
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
  onSnapshot: (messages: ThreadMessageLike[]) => void;
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
      onSnapshot(event.messages ?? []);
    }
  }
};
