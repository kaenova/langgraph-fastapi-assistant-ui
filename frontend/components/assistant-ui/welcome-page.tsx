"use client";

import { useMemo, useState, type FC } from "react";
import { useRouter } from "next/navigation";
import {
  AssistantRuntimeProvider,
  AuiIf,
  ComposerPrimitive,
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { ArrowUpIcon, SquareIcon } from "lucide-react";

import {
  ComposerAddAttachment,
  ComposerAttachments,
} from "@/components/assistant-ui/attachment";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Button } from "@/components/ui/button";
import {
  WELCOME_INITIAL_MESSAGE_KEY_PREFIX,
  createAttachmentAdapter,
  toBackendMessageInput,
} from "@/lib/external-store-chat";

export const WelcomePage: FC = () => {
  const router = useRouter();
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const attachmentAdapter = useMemo(createAttachmentAdapter, []);

  const runtime = useExternalStoreRuntime<ThreadMessageLike>({
    isRunning,
    messages: [],
    convertMessage: (message) => message,
    onNew: async (message: AppendMessage) => {
      setError(null);
      setIsRunning(true);
      try {
        const threadId = crypto.randomUUID();
        sessionStorage.setItem(
          `${WELCOME_INITIAL_MESSAGE_KEY_PREFIX}${threadId}`,
          JSON.stringify(toBackendMessageInput(message)),
        );
        router.push(`/chat/${encodeURIComponent(threadId)}`);
      } catch (newMessageError) {
        setError(
          newMessageError instanceof Error
            ? newMessageError.message
            : "Failed to start conversation",
        );
        setIsRunning(false);
      }
    },
    onCancel: async () => {
      setIsRunning(false);
    },
    adapters: {
      attachments: attachmentAdapter,
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <main className="flex h-dvh items-center justify-center bg-background px-4">
        <div className="w-full max-w-2xl space-y-4">
          <h1 className="text-center font-semibold text-3xl">Welcome</h1>
          <p className="text-center text-muted-foreground text-sm">
            Start a new conversation.
          </p>
          <WelcomeComposer />
          {error ? <p className="text-destructive text-sm">{error}</p> : null}
        </div>
      </main>
    </AssistantRuntimeProvider>
  );
};

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
