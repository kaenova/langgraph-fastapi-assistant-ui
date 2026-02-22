Here are a reference for Welcome Page for implementation:
```tsx
"use client";

import { useMemo, useState, type FC } from "react";
import { useRouter } from "next/navigation";
import {
  AssistantRuntimeProvider,
  AuiIf,
  ComposerPrimitive,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { ArrowUpIcon, SquareIcon } from "lucide-react";

import {
  ComposerAddAttachment,
  ComposerAttachments,
} from "@/components/assistant-ui/attachment";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Button } from "@/components/ui/button";

import {
  THREAD_API_INITIALIZE,
  WELCOME_INITIAL_MESSAGE_KEY_PREFIX,
} from "./constants";
import { useTemplateLocalRuntime } from "./runtime/use-template-local-runtime";
import type { WelcomeInitialMessagePayload } from "./types";

// Renders the landing composer and bootstraps a new thread on first send.
export const WelcomePage = () => {
  const router = useRouter();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Captures the welcome input, creates a thread, stores payload, and redirects.
  const modelAdapter = useMemo<ChatModelAdapter>(
    () => ({
      async run({ messages, abortSignal }) {
        setErrorMessage(null);
        const latestUserMessage = [...messages]
          .reverse()
          .find(
            (
              message,
            ): message is Extract<(typeof messages)[number], { role: "user" }> =>
              message.role === "user",
          );

        if (!latestUserMessage) {
          return { content: [] };
        }

        const threadId = crypto.randomUUID();
        const payload: WelcomeInitialMessagePayload = {
          content: [...latestUserMessage.content],
          attachments: [...latestUserMessage.attachments],
        };

        try {
          const response = await fetch(THREAD_API_INITIALIZE, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ threadId }),
            signal: abortSignal,
          });

          if (!response.ok) {
            const errorText = await response.text();
            throw new Error(errorText || "Failed to initialize thread");
          }

          sessionStorage.setItem(
            `${WELCOME_INITIAL_MESSAGE_KEY_PREFIX}${threadId}`,
            JSON.stringify(payload),
          );
          router.push(`/chat/${encodeURIComponent(threadId)}`);
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") {
            return { content: [] };
          }
          setErrorMessage(
            error instanceof Error
              ? error.message
              : "Failed to start conversation",
          );
        }

        return { content: [] };
      },
    }),
    [router],
  );
  const runtime = useTemplateLocalRuntime({ modelAdapter });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <main className="flex h-full items-center justify-center bg-background px-4">
        <div className="w-full max-w-2xl space-y-4">
          <h1 className="text-center font-semibold text-3xl">Welcome</h1>
          <p className="text-center text-muted-foreground text-sm">
            Start a new conversation.
          </p>
          <WelcomeComposer />
          {errorMessage ? (
            <p className="text-destructive text-sm">{errorMessage}</p>
          ) : null}
        </div>
      </main>
    </AssistantRuntimeProvider>
  );
};

// Reuses chat composer UX on welcome while sending through local runtime.
const WelcomeComposer: FC = () => {
  return (
    <ComposerPrimitive.Root className="relative flex w-full flex-col">
      <ComposerPrimitive.AttachmentDropzone className="flex w-full flex-col rounded-2xl border border-input px-1 pt-2 outline-none transition-shadow has-[textarea:focus-visible]:border-ring has-[textarea:focus-visible]:ring-2 has-[textarea:focus-visible]:ring-ring/20 data-[dragging=true]:border-ring data-[dragging=true]:border-dashed data-[dragging=true]:bg-accent/50">
        <ComposerAttachments />
        <ComposerPrimitive.Input
          placeholder="Send a message..."
          className="mb-1 min-h-14 w-full resize-none bg-transparent px-4 pt-2 pb-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-0"
          rows={1}
          autoFocus
          aria-label="Welcome message input"
        />
        <div className="relative mx-2 mb-2 flex items-center justify-between">
          <ComposerAddAttachment />
          <AuiIf condition={({ thread }) => !thread.isRunning}>
            <ComposerPrimitive.Send asChild>
              <TooltipIconButton
                tooltip="Start chat"
                side="bottom"
                type="submit"
                variant="default"
                size="icon"
                className="size-8 rounded-full"
                aria-label="Start chat"
              >
                <ArrowUpIcon className="size-4" />
              </TooltipIconButton>
            </ComposerPrimitive.Send>
          </AuiIf>
          <AuiIf condition={({ thread }) => thread.isRunning}>
            <ComposerPrimitive.Cancel asChild>
              <Button
                type="button"
                variant="default"
                size="icon"
                className="size-8 rounded-full"
                aria-label="Stop generating"
              >
                <SquareIcon className="size-3 fill-current" />
              </Button>
            </ComposerPrimitive.Cancel>
          </AuiIf>
        </div>
      </ComposerPrimitive.AttachmentDropzone>
    </ComposerPrimitive.Root>
  );
};
```
