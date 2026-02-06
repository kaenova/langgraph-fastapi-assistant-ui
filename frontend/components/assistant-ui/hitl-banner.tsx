"use client";

import { useRef, useState } from "react";
import { useAuiState, useAuiEvent } from "@assistant-ui/react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AlertCircleIcon, CheckIcon, XIcon } from "lucide-react";
import { useHitl } from "./MyRuntimeProvider";

export function HitlApprovalBanner() {
  const { pendingInterrupt, sendFeedback, resetInterrupt } = useHitl();

  // Track per-tool-call decisions: "approved" | "rejected" | undefined (undecided)
  const [decisions, setDecisions] = useState<
    Record<string, "approved" | "rejected">
  >({});

  // Reset decisions when the interrupt changes
  const prevInterruptRef = useRef(pendingInterrupt);
  if (prevInterruptRef.current !== pendingInterrupt) {
    prevInterruptRef.current = pendingInterrupt;
    setDecisions({});
  }

  useAuiEvent("composer.send", (event) => {
    resetInterrupt();
  });

  if (!pendingInterrupt) return null;

  const toolCalls = pendingInterrupt.tool_calls;

  const allDecided = toolCalls.every((tc) => tc.id in decisions);

  const handleDecision = (id: string, decision: "approved" | "rejected") => {
    setDecisions((prev) => ({ ...prev, [id]: decision }));
  };

  const handleSendFeedback = () => {
    if (!allDecided) return;
    sendFeedback({
      approved_ids: toolCalls
        .filter((tc) => decisions[tc.id] === "approved")
        .map((tc) => tc.id),
      rejected_ids: toolCalls
        .filter((tc) => decisions[tc.id] === "rejected")
        .map((tc) => tc.id),
    });
  };

  return (
    <div className="mx-auto w-full pb-2">
      <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-4">
        <div className="mb-3 flex items-center gap-2 text-yellow-500">
          <AlertCircleIcon className="size-5" />
          <span className="font-semibold text-sm">Approval Required</span>
        </div>

        <div className="mb-3 space-y-2">
          {toolCalls.map((tc) => {
            const decision = decisions[tc.id];
            return (
              <div
                key={tc.id}
                className={cn(
                  "rounded-md border p-3 transition-colors",
                  decision === "approved"
                    ? "border-green-500/40 bg-green-500/5"
                    : decision === "rejected"
                      ? "border-red-500/40 bg-red-500/5"
                      : "border-border bg-background",
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm">{tc.name}</p>
                    <pre className="mt-1 whitespace-pre-wrap text-muted-foreground text-xs">
                      {JSON.stringify(tc.arguments, null, 2)}
                    </pre>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button
                      size="sm"
                      variant={decision === "approved" ? "default" : "outline"}
                      onClick={() => handleDecision(tc.id, "approved")}
                      className="h-7 gap-1 px-2 text-xs"
                    >
                      <CheckIcon className="size-3" />
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant={
                        decision === "rejected" ? "destructive" : "outline"
                      }
                      onClick={() => handleDecision(tc.id, "rejected")}
                      className="h-7 gap-1 px-2 text-xs"
                    >
                      <XIcon className="size-3" />
                      Reject
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <Button
          size="sm"
          variant="default"
          onClick={handleSendFeedback}
          disabled={!allDecided}
          className="w-full gap-1"
        >
          <CheckIcon className="size-3.5" />
          Send Feedback
        </Button>
      </div>
    </div>
  );
}
