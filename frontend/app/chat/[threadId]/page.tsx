"use client";

import { useParams, useSearchParams } from "next/navigation";

import { LocalRuntimeProvider } from "@/components/assistant-ui/runtime-provider";

export default function ChatThreadPage() {
  const params = useParams<{ threadId: string }>();
  const searchParams = useSearchParams();
  const initialPrompt = searchParams.get("q") ?? undefined;

  return (
    <LocalRuntimeProvider
      threadId={params.threadId}
      initialPrompt={initialPrompt}
    />
  );
}
