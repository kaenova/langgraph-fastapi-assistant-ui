import type { ThreadHistoryAdapter } from "@assistant-ui/react";
import type { ReadonlyJSONObject } from "assistant-stream/utils";

export type BackendEvent =
  | { type: "text_delta"; delta: string }
  | {
      type: "tool_call";
      toolCallId: string;
      toolName: string;
      args: ReadonlyJSONObject;
      argsText?: string;
    }
  | {
      type: "tool_result";
      toolCallId: string;
      result: unknown;
      isError?: boolean;
    }
  | { type: "done"; status: "complete" | "requires-action" }
  | { type: "error"; message: string };

export type HistoryRepository = {
  headId?: string | null;
  messages: Array<{
    message: Record<string, unknown>;
    parentId: string | null;
    runConfig?: Record<string, unknown>;
  }>;
};

export type LocalHistoryLoadResult = Awaited<
  ReturnType<ThreadHistoryAdapter["load"]>
>;
