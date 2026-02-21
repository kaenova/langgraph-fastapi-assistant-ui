"use client";

import { useParams } from "next/navigation";

import { LocalRuntimeProvider } from "@/components/assistant-ui/runtime-provider";

export default function ChatThreadPage() {
  const params = useParams<{ threadId: string }>();

  return <LocalRuntimeProvider threadId={params.threadId} />;
}
