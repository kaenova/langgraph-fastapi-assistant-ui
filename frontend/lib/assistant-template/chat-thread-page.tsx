"use client";

import { useParams } from "next/navigation";

import { LocalRuntimeProvider } from "@/lib/assistant-template/runtime/local-runtime-provider";

// Resolves the route threadId and mounts the runtime for that thread.
export const ChatThreadPage = () => {
  const params = useParams<{ threadId: string }>();
  return <LocalRuntimeProvider threadId={params.threadId} />;
};
