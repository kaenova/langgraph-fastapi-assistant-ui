"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";

const THREAD_API_INITIALIZE = "/api/be/api/v1/threads/initialize";

export const WelcomePage = () => {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt || isSubmitting) return;

    setIsSubmitting(true);
    setErrorMessage(null);

    const threadId = crypto.randomUUID();
    try {
      const response = await fetch(THREAD_API_INITIALIZE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threadId }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || "Failed to initialize thread");
      }

      router.push(
        `/chat/${encodeURIComponent(threadId)}?q=${encodeURIComponent(trimmedPrompt)}`,
      );
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Failed to start conversation",
      );
      setIsSubmitting(false);
    }
  };

  return (
    <main className="flex h-dvh items-center justify-center bg-background px-4">
      <div className="w-full max-w-2xl space-y-4">
        <h1 className="text-center font-semibold text-3xl">Welcome</h1>
        <p className="text-center text-muted-foreground text-sm">
          Start a new conversation.
        </p>
        <form className="space-y-3" onSubmit={handleSubmit}>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            className="min-h-40 w-full resize-y rounded-xl border bg-background px-4 py-3 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
            placeholder="Type your message..."
            aria-label="Welcome message input"
            autoFocus
          />
          {errorMessage ? (
            <p className="text-destructive text-sm">{errorMessage}</p>
          ) : null}
          <div className="flex justify-end">
            <Button
              type="submit"
              disabled={isSubmitting || !prompt.trim()}
            >
              {isSubmitting ? "Starting..." : "Start chat"}
            </Button>
          </div>
        </form>
      </div>
    </main>
  );
};
