"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageSquareIcon, RefreshCwIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { THREAD_API_BASE, requestJson } from "./runtime/thread-api";

type ThreadListItem = {
  status: "regular" | "archived";
  remoteId: string;
  externalId?: string;
  title?: string;
};

type ThreadListResponse = {
  threads: ThreadListItem[];
};

// Shared app shell that renders thread navigation and page content side-by-side.
export const AssistantTemplateShellLayout = ({
  children,
}: {
  children: ReactNode;
}) => {
  const pathname = usePathname();
  const [threads, setThreads] = useState<ThreadListItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const activeThreadId = useMemo(() => {
    if (!pathname.startsWith("/chat/")) return null;
    const encodedThreadId = pathname.slice("/chat/".length);
    return encodedThreadId ? decodeURIComponent(encodedThreadId) : null;
  }, [pathname]);

  // Loads persisted thread metadata for sidebar navigation.
  const loadThreads = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await requestJson<ThreadListResponse>(THREAD_API_BASE);
      setThreads(response.threads);
    } catch {
      setThreads([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadThreads();
  }, [loadThreads, pathname]);

  return (
    <div className="flex h-dvh w-full bg-background">
      <aside className="flex h-full w-72 shrink-0 flex-col border-r bg-muted/20">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <Button asChild variant="default" size="sm">
            <Link href="/">New chat</Link>
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={() => void loadThreads()}
            aria-label="Refresh thread list"
          >
            <RefreshCwIcon className={cn("size-4", isLoading && "animate-spin")} />
          </Button>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto p-2">
          {threads.map((thread) => (
            <Link
              key={thread.remoteId}
              href={`/chat/${encodeURIComponent(thread.remoteId)}`}
              className={cn(
                "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent",
                activeThreadId === thread.remoteId && "bg-accent text-accent-foreground",
              )}
            >
              <MessageSquareIcon className="size-4 shrink-0" />
              <span className="truncate">
                {thread.title?.trim() || thread.remoteId}
              </span>
            </Link>
          ))}
          {!isLoading && threads.length === 0 ? (
            <p className="px-2 py-1 text-muted-foreground text-xs">
              No threads yet.
            </p>
          ) : null}
        </nav>
      </aside>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
};
