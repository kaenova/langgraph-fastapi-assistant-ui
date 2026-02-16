"use client";

import { ToolResponse } from "assistant-stream";
import { CloudSunIcon, ShieldAlertIcon, ShieldCheckIcon } from "lucide-react";
import { useAui, type ToolCallMessagePartStatus } from "@assistant-ui/react";
import { memo, useEffect, useMemo, useState } from "react";

import { cn } from "@/lib/utils";
import { useHitl } from "@/components/assistant-ui/CustomLanggraphRuntime";

function normalizeToolResult(result: unknown) {
  if (result === null || result === undefined) return result;
  if (typeof result === "object") {
    if ("content" in result) {
      return (result as { content?: unknown }).content;
    }
    return result;
  }
  if (typeof result === "string") {
    const trimmed = result.trim();
    if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
      try {
        const parsed = JSON.parse(trimmed);
        if (parsed && typeof parsed === "object" && "content" in parsed) {
          return (parsed as any).content;
        }
      } catch {
        // ignore
      }
    }
    const match = trimmed.match(/content=(["'])(.*?)\1/);
    if (match && match[2]) return match[2];
    return result;
  }
  return result;
}

function safeParseJsonObject(text: string): { value: Record<string, any> | null } {
  try {
    const parsed = JSON.parse(text) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return { value: null };
    return { value: parsed as Record<string, any> };
  } catch {
    return { value: null };
  }
}

function statusLabel(status?: ToolCallMessagePartStatus): string {
  const t = status?.type;
  if (!t) return "";
  if (t === "running") return "Running";
  if (t === "complete") return "Complete";
  if (t === "requires-action") return "Needs input";
  if (t === "incomplete") {
    if (status.reason === "cancelled") return "Cancelled";
    if (status.reason === "error") return "Error";
    return "Incomplete";
  }
  return "";
}

type ToolCardProps = {
  toolCallId: string;
  toolName: string;
  args: unknown;
  argsText: string;
  result?: unknown;
  status?: ToolCallMessagePartStatus;
  isError?: boolean;
};

const CurrentWeatherToolCardImpl = ({
  toolCallId,
  toolName,
  argsText,
  result,
  status,
}: ToolCardProps) => {
  const aui = useAui();
  const {
    pendingInterrupt,
    decisions,
    setDecision,
    argsDraftTextById,
    setArgsDraftText,
    resetArgsDraftText,
    argsDraftErrorById,
    allDecided,
    allApprovedArgsValid,
    submitDecisions,
    toolResults,
    argsDisplayTextById,
  } = useHitl();

  const interruptToolCalls = pendingInterrupt?.tool_calls ?? [];
  const isInterruptTool = interruptToolCalls.some((tc) => tc.id === toolCallId);
  const decision = decisions[toolCallId];
  const isLastInterruptTool =
    interruptToolCalls[interruptToolCalls.length - 1]?.id === toolCallId;

  // Prefer: live draft (interrupt) -> stored display -> original argsText
  const displayArgsText =
    (isInterruptTool ? argsDraftTextById[toolCallId] : undefined) ??
    argsDisplayTextById[toolCallId] ??
    argsText;

  const draftError = argsDraftErrorById[toolCallId] ?? null;

  // Extract city for the nice UI from the effective args JSON.
  const city = useMemo(() => {
    const parsed = safeParseJsonObject(displayArgsText ?? "{}");
    if (!parsed.value) return "";
    const maybe = parsed.value.city;
    return typeof maybe === "string" ? maybe : "";
  }, [displayArgsText]);

  const [showAdvanced, setShowAdvanced] = useState(false);

  // Backfill tool results after resume (when tool_call isn't re-emitted).
  const storedResult = toolResults[toolCallId];
  useEffect(() => {
    if (!storedResult) return;
    if (result !== undefined) return;
    aui
      .part()
      .addToolResult(
        new ToolResponse({
          result: storedResult.result,
          isError: storedResult.isError ?? false,
        }),
      );
  }, [storedResult, result, aui]);

  const hintText = isInterruptTool
    ? decision === "approved"
      ? "Approved"
      : decision === "rejected"
        ? "Rejected"
        : "Approval required"
    : null;

  const normalizedResult = result === undefined ? undefined : normalizeToolResult(result);

  const showApprovalControls =
    isInterruptTool && status?.type === "requires-action" && decision !== "rejected";

  return (
    <div
      className={cn(
        "w-full overflow-hidden rounded-xl border",
        "bg-[linear-gradient(180deg,hsl(var(--muted))_0%,hsl(var(--background))_85%)]",
        isInterruptTool && decision === "approved" && "border-green-500/40",
        isInterruptTool && decision === "rejected" && "border-red-500/40",
        isInterruptTool && !decision && "border-amber-500/40",
      )}
      data-tool-name={toolName}
    >
      <div className="flex items-start gap-3 px-4 py-3">
        <div
          className={cn(
            "mt-0.5 flex size-9 items-center justify-center rounded-lg border",
            "bg-background/80",
            status?.type === "running" && "animate-pulse",
          )}
        >
          <CloudSunIcon className="size-5" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate font-semibold leading-none">Weather check</p>
            {city ? (
              <span className="truncate text-muted-foreground text-sm leading-none">
                for {city}
              </span>
            ) : null}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {hintText ? (
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
                  decision === "approved" && "border-green-500/40 bg-green-500/10 text-green-700",
                  decision === "rejected" && "border-red-500/40 bg-red-500/10 text-red-700",
                  !decision && "border-amber-500/40 bg-amber-500/10 text-amber-800",
                )}
              >
                {decision === "approved" ? (
                  <ShieldCheckIcon className="size-3" />
                ) : (
                  <ShieldAlertIcon className="size-3" />
                )}
                {hintText}
              </span>
            ) : null}

            {status?.type ? (
              <span className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">
                {statusLabel(status)}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      {isInterruptTool ? (
        <div className="border-t bg-background/70 px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setDecision(toolCallId, "approved")}
              className={cn(
                "rounded-md border px-2.5 py-1 text-xs transition-colors",
                decision === "approved"
                  ? "border-green-500/50 bg-green-500/10 text-green-700"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              Approve
            </button>
            <button
              type="button"
              onClick={() => setDecision(toolCallId, "rejected")}
              className={cn(
                "rounded-md border px-2.5 py-1 text-xs transition-colors",
                decision === "rejected"
                  ? "border-red-500/50 bg-red-500/10 text-red-700"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              Reject
            </button>
            <button
              type="button"
              onClick={() => resetArgsDraftText(toolCallId)}
              className="ml-auto text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
            >
              Reset args
            </button>
          </div>

          {decision === "rejected" && result === undefined ? (
            <p className="mt-2 text-xs text-muted-foreground">
              This tool call will not run.
            </p>
          ) : null}

          {showApprovalControls ? (
            <div className="mt-3">
              <label className="text-xs font-semibold text-muted-foreground">City</label>
              <input
                value={city}
                onChange={(e) => {
                  const baseText = argsDraftTextById[toolCallId] ?? displayArgsText ?? "{}";
                  const parsed = safeParseJsonObject(baseText).value ?? {};
                  parsed.city = e.target.value;
                  setArgsDraftText(toolCallId, JSON.stringify(parsed, null, 2));
                }}
                placeholder="e.g. San Francisco"
                className={cn(
                  "mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                )}
              />

              <div className="mt-2 flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => setShowAdvanced((v) => !v)}
                  className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
                >
                  {showAdvanced ? "Hide" : "Show"} advanced JSON
                </button>
                {draftError ? (
                  <span className="text-xs text-red-600">{draftError}</span>
                ) : null}
              </div>

              {showAdvanced ? (
                <textarea
                  value={argsDraftTextById[toolCallId] ?? displayArgsText ?? "{}"}
                  onChange={(e) => setArgsDraftText(toolCallId, e.target.value)}
                  spellCheck={false}
                  className={cn(
                    "mt-2 w-full resize-y rounded-md border bg-background px-2 py-1.5 font-mono text-xs leading-5",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    draftError && "border-red-500/50",
                  )}
                  rows={6}
                />
              ) : null}

              {isLastInterruptTool ? (
                <div className="mt-3">
                  <button
                    type="button"
                    onClick={submitDecisions}
                    disabled={!allDecided || !allApprovedArgsValid}
                    className={cn(
                      "w-full rounded-md border px-3 py-2 text-xs font-medium",
                      allDecided && allApprovedArgsValid
                        ? "border-foreground/20 bg-foreground text-background"
                        : "border-border text-muted-foreground",
                    )}
                  >
                    Send Feedback
                  </button>
                  {allDecided && !allApprovedArgsValid ? (
                    <p className="mt-2 text-xs text-muted-foreground">
                      Fix argument JSON for approved tool calls to continue.
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {normalizedResult !== undefined ? (
        <div className="border-t bg-background px-4 py-3">
          <p className="text-xs font-semibold text-muted-foreground">Result</p>
          <pre className="mt-1 whitespace-pre-wrap text-sm">
            {typeof normalizedResult === "string"
              ? normalizedResult
              : JSON.stringify(normalizedResult, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
};

export const CurrentWeatherToolCard = memo(CurrentWeatherToolCardImpl);
