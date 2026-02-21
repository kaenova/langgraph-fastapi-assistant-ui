import type { CompleteAttachment, ThreadUserMessagePart } from "@assistant-ui/react";

export type WelcomeInitialMessagePayload = {
  content: ThreadUserMessagePart[];
  attachments: CompleteAttachment[];
};
