"use client";

import type { FC } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";

import { Thread } from "@/components/assistant-ui/thread";
import { useWeatherAssistantRuntime } from "@/app/runtime-provider";

interface AssistantProps {
  threadId?: string | null;
}

export const Assistant: FC<AssistantProps> = ({ threadId = null }) => {
  const runtime = useWeatherAssistantRuntime(threadId);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="h-dvh">
        <Thread />
      </div>
    </AssistantRuntimeProvider>
  );
};
