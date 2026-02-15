"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircleIcon,
  CheckIcon,
  ChevronDownIcon,
  LoaderIcon,
  XCircleIcon,
} from "lucide-react";
import {
  useAui,
  useScrollLock,
  type ToolCallMessagePartStatus,
  type ToolCallMessagePartComponent,
} from "@assistant-ui/react";
import { ToolResponse } from "assistant-stream";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { useHitl } from "./MyRuntimeProvider";

const ANIMATION_DURATION = 200;

export type ToolFallbackRootProps = Omit<
  React.ComponentProps<typeof Collapsible>,
  "open" | "onOpenChange"
> & {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  defaultOpen?: boolean;
};

function ToolFallbackRoot({
  className,
  open: controlledOpen,
  onOpenChange: controlledOnOpenChange,
  defaultOpen = false,
  children,
  ...props
}: ToolFallbackRootProps) {
  const collapsibleRef = useRef<HTMLDivElement>(null);
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const lockScroll = useScrollLock(collapsibleRef, ANIMATION_DURATION);

  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;

  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (!open) {
        lockScroll();
      }
      if (!isControlled) {
        setUncontrolledOpen(open);
      }
      controlledOnOpenChange?.(open);
    },
    [lockScroll, isControlled, controlledOnOpenChange],
  );

  return (
    <Collapsible
      ref={collapsibleRef}
      data-slot="tool-fallback-root"
      open={isOpen}
      onOpenChange={handleOpenChange}
      className={cn(
        "aui-tool-fallback-root group/tool-fallback-root w-full rounded-lg border py-3",
        className,
      )}
      style={
        {
          "--animation-duration": `${ANIMATION_DURATION}ms`,
        } as React.CSSProperties
      }
      {...props}
    >
      {children}
    </Collapsible>
  );
}

type ToolStatus = ToolCallMessagePartStatus["type"];

const statusIconMap: Record<ToolStatus, React.ElementType> = {
  running: LoaderIcon,
  complete: CheckIcon,
  incomplete: XCircleIcon,
  "requires-action": AlertCircleIcon,
};

function ToolFallbackTrigger({
  toolName,
  status,
  hint,
  className,
  ...props
}: React.ComponentProps<typeof CollapsibleTrigger> & {
  toolName: string;
  status?: ToolCallMessagePartStatus;
  hint?: React.ReactNode;
}) {
  const statusType = status?.type ?? "complete";
  const isRunning = statusType === "running";
  const isCancelled =
    status?.type === "incomplete" && status.reason === "cancelled";

  const Icon = statusIconMap[statusType];
  const label = isCancelled ? "Cancelled tool" : "Used tool";

  return (
    <CollapsibleTrigger
      data-slot="tool-fallback-trigger"
      className={cn(
        "aui-tool-fallback-trigger group/trigger flex w-full items-center gap-2 px-4 text-sm transition-colors",
        className,
      )}
      {...props}
    >
      <Icon
        data-slot="tool-fallback-trigger-icon"
        className={cn(
          "aui-tool-fallback-trigger-icon size-4 shrink-0",
          isCancelled && "text-muted-foreground",
          isRunning && "animate-spin",
        )}
      />
      <span
        data-slot="tool-fallback-trigger-label"
        className={cn(
          "aui-tool-fallback-trigger-label-wrapper relative inline-block grow text-left leading-none",
          isCancelled && "text-muted-foreground line-through",
        )}
      >
        <span>
          {label}: <b>{toolName}</b>
        </span>
        {isRunning && (
          <span
            aria-hidden
            data-slot="tool-fallback-trigger-shimmer"
            className="aui-tool-fallback-trigger-shimmer shimmer pointer-events-none absolute inset-0 motion-reduce:animate-none"
          >
            {label}: <b>{toolName}</b>
          </span>
        )}
      </span>
      {hint ? (
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide",
            "text-muted-foreground",
            "group-data-[state=open]/trigger:opacity-0",
            "group-data-[state=open]/trigger:pointer-events-none",
          )}
        >
          {hint}
        </span>
      ) : null}
      <ChevronDownIcon
        data-slot="tool-fallback-trigger-chevron"
        className={cn(
          "aui-tool-fallback-trigger-chevron size-4 shrink-0",
          "transition-transform duration-(--animation-duration) ease-out",
          "group-data-[state=closed]/trigger:-rotate-90",
          "group-data-[state=open]/trigger:rotate-0",
        )}
      />
    </CollapsibleTrigger>
  );
}

function ToolFallbackContent({
  className,
  children,
  ...props
}: React.ComponentProps<typeof CollapsibleContent>) {
  return (
    <CollapsibleContent
      data-slot="tool-fallback-content"
      className={cn(
        "aui-tool-fallback-content relative overflow-hidden text-sm outline-none",
        "group/collapsible-content ease-out",
        "data-[state=closed]:animate-collapsible-up",
        "data-[state=open]:animate-collapsible-down",
        "data-[state=closed]:fill-mode-forwards",
        "data-[state=closed]:pointer-events-none",
        "data-[state=open]:duration-(--animation-duration)",
        "data-[state=closed]:duration-(--animation-duration)",
        className,
      )}
      {...props}
    >
      <div className="mt-3 flex flex-col gap-2 border-t pt-2">{children}</div>
    </CollapsibleContent>
  );
}

function ToolFallbackArgs({
  argsText,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  argsText?: string;
}) {
  if (!argsText) return null;

  return (
    <div
      data-slot="tool-fallback-args"
      className={cn("aui-tool-fallback-args px-4", className)}
      {...props}
    >
      <pre className="aui-tool-fallback-args-value whitespace-pre-wrap">
        {argsText}
      </pre>
    </div>
  );
}

function ToolFallbackResult({
  result,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  result?: unknown;
}) {
  if (result === undefined) return null;

  const normalizedResult = normalizeToolResult(result);

  return (
    <div
      data-slot="tool-fallback-result"
      className={cn(
        "aui-tool-fallback-result border-t border-dashed px-4 pt-2",
        className,
      )}
      {...props}
    >
      <p className="aui-tool-fallback-result-header font-semibold">Result:</p>
      <pre className="aui-tool-fallback-result-content whitespace-pre-wrap">
        {typeof normalizedResult === "string"
          ? normalizedResult
          : JSON.stringify(normalizedResult, null, 2)}
      </pre>
    </div>
  );
}

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
          return parsed.content;
        }
      } catch {
        // ignore JSON parse errors
      }
    }
    const match = trimmed.match(/content=(["'])(.*?)\1/);
    if (match && match[2]) return match[2];
    return result;
  }
  return result;
}

function ToolFallbackError({
  status,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  status?: ToolCallMessagePartStatus;
}) {
  if (status?.type !== "incomplete") return null;

  const error = status.error;
  const errorText = error
    ? typeof error === "string"
      ? error
      : JSON.stringify(error)
    : null;

  if (!errorText) return null;

  const isCancelled = status.reason === "cancelled";
  const headerText = isCancelled ? "Cancelled reason:" : "Error:";

  return (
    <div
      data-slot="tool-fallback-error"
      className={cn("aui-tool-fallback-error px-4", className)}
      {...props}
    >
      <p className="aui-tool-fallback-error-header font-semibold text-muted-foreground">
        {headerText}
      </p>
      <p className="aui-tool-fallback-error-reason text-muted-foreground">
        {errorText}
      </p>
    </div>
  );
}

const ToolFallbackImpl: ToolCallMessagePartComponent = ({
  toolCallId,
  toolName,
  argsText,
  result,
  status,
}) => {
  const isCancelled =
    status?.type === "incomplete" && status.reason === "cancelled";
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

  const displayArgsText =
    (isInterruptTool ? argsDraftTextById[toolCallId] : undefined) ??
    argsDisplayTextById[toolCallId] ??
    argsText;
  const draftError = argsDraftErrorById[toolCallId] ?? null;

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

  const hint = isInterruptTool
    ? decision === "approved"
      ? "Approved"
      : decision === "rejected"
        ? "Rejected"
        : "Needs approval"
    : undefined;

  return (
    <ToolFallbackRoot
      className={cn(
        isCancelled && "border-muted-foreground/30 bg-muted/30",
        decision === "approved" && "border-green-500/40 bg-green-500/5",
        decision === "rejected" && "border-red-500/40 bg-red-500/5",
      )}
    >
      <ToolFallbackTrigger toolName={toolName} status={status} hint={hint} />
      <ToolFallbackContent>
        <ToolFallbackError status={status} />
        {isInterruptTool && !isCancelled ? (
          <div className="px-4">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-semibold text-muted-foreground">
                Arguments (editable):
              </p>
              <button
                type="button"
                onClick={() => resetArgsDraftText(toolCallId)}
                className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
              >
                Reset
              </button>
            </div>
            <textarea
              value={argsDraftTextById[toolCallId] ?? displayArgsText ?? "{}"}
              onChange={(e) => setArgsDraftText(toolCallId, e.target.value)}
              disabled={decision === "rejected"}
              spellCheck={false}
              className={cn(
                "mt-1 w-full resize-y rounded-md border bg-background px-2 py-1.5 font-mono text-xs leading-5",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                decision === "rejected" && "opacity-60",
                draftError && decision !== "rejected" && "border-red-500/50",
              )}
              rows={6}
            />
            {draftError && decision !== "rejected" ? (
              <p className="mt-1 text-xs text-red-600">{draftError}</p>
            ) : null}
          </div>
        ) : null}
        {!isInterruptTool ? (
          <ToolFallbackArgs
            argsText={displayArgsText}
            className={cn(isCancelled && "opacity-60")}
          />
        ) : isCancelled ? (
          <ToolFallbackArgs
            argsText={displayArgsText}
            className={cn(isCancelled && "opacity-60")}
          />
        ) : null}
        {isInterruptTool && (
          <div className="flex flex-col gap-2 px-4">
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setDecision(toolCallId, "approved")}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-xs transition-colors",
                  decision === "approved"
                    ? "border-green-500/50 bg-green-500/10 text-green-600"
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
                    ? "border-red-500/50 bg-red-500/10 text-red-600"
                    : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                Reject
              </button>
            </div>
            {decision === "rejected" && result === undefined && (
              <p className="text-muted-foreground text-xs">
                This tool call will not run.
              </p>
            )}
            {isLastInterruptTool && (
              <button
                type="button"
                onClick={submitDecisions}
                disabled={!allDecided || !allApprovedArgsValid}
                className={cn(
                  "mt-1 rounded-md border px-3 py-1.5 text-xs font-medium",
                  allDecided && allApprovedArgsValid
                    ? "border-foreground/20 bg-foreground text-background"
                    : "border-border text-muted-foreground",
                )}
              >
                Send Feedback
              </button>
            )}
            {isLastInterruptTool && allDecided && !allApprovedArgsValid ? (
              <p className="text-xs text-muted-foreground">
                Fix argument JSON for approved tool calls to continue.
              </p>
            ) : null}
          </div>
        )}
        {!isCancelled && <ToolFallbackResult result={result} />}
      </ToolFallbackContent>
    </ToolFallbackRoot>
  );
};

const ToolFallback = memo(
  ToolFallbackImpl,
) as unknown as ToolCallMessagePartComponent & {
  Root: typeof ToolFallbackRoot;
  Trigger: typeof ToolFallbackTrigger;
  Content: typeof ToolFallbackContent;
  Args: typeof ToolFallbackArgs;
  Result: typeof ToolFallbackResult;
  Error: typeof ToolFallbackError;
};

ToolFallback.displayName = "ToolFallback";
ToolFallback.Root = ToolFallbackRoot;
ToolFallback.Trigger = ToolFallbackTrigger;
ToolFallback.Content = ToolFallbackContent;
ToolFallback.Args = ToolFallbackArgs;
ToolFallback.Result = ToolFallbackResult;
ToolFallback.Error = ToolFallbackError;

export {
  ToolFallback,
  ToolFallbackRoot,
  ToolFallbackTrigger,
  ToolFallbackContent,
  ToolFallbackArgs,
  ToolFallbackResult,
  ToolFallbackError,
};
