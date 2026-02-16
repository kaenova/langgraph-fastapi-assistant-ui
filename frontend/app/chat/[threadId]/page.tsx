"use client";

import { useEffect } from "react";
import { useParams } from "next/navigation";

import { Assistant } from "@/app/assistant";
import { useAui } from "@assistant-ui/react";

const PendingMessageSender = ({ threadId }: { threadId: string }) => {
  const aui = useAui();

  useEffect(() => {
    if (typeof window === "undefined") return;
    const key = `pending_message:${threadId}`;
    const pending = sessionStorage.getItem(key);
    if (!pending) return;
    sessionStorage.removeItem(key);
    aui.thread().append({
      role: "user",
      content: [{ type: "text", text: pending }],
      startRun: true,
    });
  }, [aui, threadId]);

  return null;
};

export default function ChatThreadPage() {
  const params = useParams();
  const rawThreadId = typeof params.threadId === "string" ? params.threadId : "";
  const threadId = rawThreadId ? rawThreadId : undefined;

  if (!threadId) {
    return null;
  }

  return (
    <Assistant threadId={threadId}>
      {threadId ? <PendingMessageSender threadId={threadId} /> : null}
    </Assistant>
  );
}
