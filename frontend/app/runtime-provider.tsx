"use client";

import {
  ExportedMessageRepository,
  type AddToolResultOptions,
  type AppendMessage,
  type MessageStatus,
  type ThreadAssistantMessagePart,
  type ThreadMessage,
  type ThreadUserMessagePart,
  useExternalStoreRuntime,
} from "@assistant-ui/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createThread,
  getThreadState,
  sendAssistantCommands,
  type AssistantCommandPayload,
  type AssistantMessagePayload,
  type StreamOperation,
} from "@/lib/chat-api";

const DEFAULT_BRANCH_ID = "branch-main";
const PENDING_WELCOME_MESSAGE_KEY = "assistant-ui.pending-welcome-message";

type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };
type JsonRecord = { [key: string]: JsonValue };
type JsonPath = Array<string | number>;

interface BackendMessage {
  id: string;
  role: string;
  content: Array<Record<string, unknown>>;
  parent_id?: string | null;
  branch_id?: string;
  created_at?: number;
}

interface BackendThreadState {
  thread: {
    id: string | null;
    title: string | null;
    status: string;
  };
  messages: BackendMessage[];
  interrupts: JsonRecord[];
  head_id: string | null;
  ui: {
    route: string;
  };
}

interface PendingWelcomeMessage {
  threadId: string;
  message: AssistantMessagePayload;
}

const isJsonRecord = (value: unknown): value is JsonRecord => {
  return typeof value === "object" && value !== null && !Array.isArray(value);
};

const getString = (value: unknown): string | null => {
  return typeof value === "string" ? value : null;
};

const getThreadRoute = (threadId: string | null): string => {
  if (!threadId) return "/";
  return `/chat/${threadId}`;
};

const createDraftState = (threadId: string | null): BackendThreadState => {
  return {
    thread: {
      id: threadId,
      title: null,
      status: threadId ? "regular" : "draft",
    },
    messages: [],
    interrupts: [],
    head_id: null,
    ui: {
      route: getThreadRoute(threadId),
    },
  };
};

const toEpochSeconds = (): number => Math.floor(Date.now() / 1000);

const normalizeBackendState = (
  rawState: unknown,
  threadId: string,
  title: string | null,
  status: string,
): BackendThreadState => {
  const draft = createDraftState(threadId);
  if (!isJsonRecord(rawState)) {
    return {
      ...draft,
      thread: {
        id: threadId,
        title,
        status,
      },
    };
  }

  const messages = Array.isArray(rawState.messages)
    ? rawState.messages.flatMap((item) => {
        if (!isJsonRecord(item)) return [];
        const id = getString(item.id);
        const role = getString(item.role);
        if (!id || !role) return [];
        const content = Array.isArray(item.content)
          ? item.content.filter((part): part is JsonRecord => isJsonRecord(part))
          : [];
        const parentId = getString(item.parent_id);
        const branchId = getString(item.branch_id);
        const createdAt =
          typeof item.created_at === "number" ? item.created_at : undefined;

        return [
          {
            id,
            role,
            content,
            ...(parentId ? { parent_id: parentId } : {}),
            ...(branchId ? { branch_id: branchId } : {}),
            ...(createdAt ? { created_at: createdAt } : {}),
          } satisfies BackendMessage,
        ];
      })
    : [];
  const interrupts = Array.isArray(rawState.interrupts)
    ? rawState.interrupts.filter(
        (item): item is JsonRecord => isJsonRecord(item),
      )
    : [];
  const headId = getString(rawState.head_id);

  return {
    thread: {
      id: threadId,
      title:
        getString((rawState.thread as JsonRecord | undefined)?.title) ?? title,
      status:
        getString((rawState.thread as JsonRecord | undefined)?.status) ?? status,
    },
    messages,
    interrupts,
    head_id: headId,
    ui: {
      route: getString((rawState.ui as JsonRecord | undefined)?.route) ?? getThreadRoute(threadId),
    },
  };
};

const containerFor = (nextKey: string | number): JsonValue => {
  return Number.isInteger(nextKey) ? [] : {};
};

const setByPath = (
  target: JsonRecord | JsonValue[],
  path: JsonPath,
  value: JsonValue,
) => {
  let current: unknown = target;
  for (let index = 0; index < path.length - 1; index += 1) {
    const key = path[index];
    const nextKey = path[index + 1];

    if (typeof key === "number") {
      if (!Array.isArray(current)) {
        throw new TypeError(`Expected array while traversing ${path.join(".")}`);
      }
      while (current.length <= key) current.push(null);
      if (current[key] === null || current[key] === undefined) {
        current[key] = containerFor(nextKey);
      }
      current = current[key] as unknown;
      continue;
    }

    if (!isJsonRecord(current)) {
      throw new TypeError(`Expected object while traversing ${path.join(".")}`);
    }
    if (!(key in current) || current[key] === null || current[key] === undefined) {
      current[key] = containerFor(nextKey);
    }
    current = current[key];
  }

  const lastKey = path[path.length - 1];
  if (typeof lastKey === "number") {
    if (!Array.isArray(current)) {
      throw new TypeError(`Expected array for final key in ${path.join(".")}`);
    }
    while (current.length <= lastKey) current.push(null);
    current[lastKey] = value;
    return;
  }

  if (!isJsonRecord(current)) {
    throw new TypeError(`Expected object for final key in ${path.join(".")}`);
  }
  current[lastKey] = value;
};

const readByPath = (target: unknown, path: JsonPath): unknown => {
  let current = target;
  for (const key of path) {
    if (typeof key === "number") {
      if (!Array.isArray(current)) {
        throw new TypeError(`Expected array while reading ${path.join(".")}`);
      }
      current = current[key];
      continue;
    }
    if (!isJsonRecord(current)) {
      throw new TypeError(`Expected object while reading ${path.join(".")}`);
    }
    current = current[key];
  }
  return current;
};

const applyOperation = (
  state: BackendThreadState,
  operation: StreamOperation,
): BackendThreadState => {
  const nextState = structuredClone(state) as BackendThreadState;
  if (operation.type === "set") {
    setByPath(
      nextState as unknown as JsonRecord,
      operation.path,
      operation.value as JsonValue,
    );
    return nextState;
  }

  const existing = readByPath(nextState, operation.path);
  const currentText = typeof existing === "string" ? existing : "";
  setByPath(
    nextState as unknown as JsonRecord,
    operation.path,
    `${currentText}${operation.value}`,
  );
  return nextState;
};

const mapAssistantStatus = (message: BackendMessage): MessageStatus => {
  const parts = Array.isArray(message.content) ? message.content : [];
  const toolCallPart = parts.find(
    (part) => isJsonRecord(part) && part.type === "tool-call",
  ) as JsonRecord | undefined;
  const statusValue = getString(toolCallPart?.status);

  if (statusValue === "requires-action") {
    return { type: "requires-action", reason: "interrupt" };
  }
  if (statusValue === "incomplete") {
    return { type: "incomplete", reason: "cancelled" };
  }
  if (statusValue === "running") {
    return { type: "running" };
  }
  return { type: "complete", reason: "unknown" };
};

const toThreadMessage = (
  message: BackendMessage,
  interruptByToolId: Map<string, JsonRecord>,
): ThreadMessage | null => {
  const createdAt = new Date((message.created_at ?? toEpochSeconds()) * 1000);
  const branchId = message.branch_id ?? DEFAULT_BRANCH_ID;
  const normalizedRole =
    message.role === "human"
      ? "user"
      : message.role === "ai"
        ? "assistant"
        : message.role;

  if (normalizedRole === "user") {
    const userContent: ThreadUserMessagePart[] = [];
    for (const part of message.content) {
      if (!isJsonRecord(part)) continue;
      if (part.type === "text" && typeof part.text === "string") {
        userContent.push({ type: "text", text: part.text });
      }
    }
    if (userContent.length === 0) {
      userContent.push({ type: "text", text: "" });
    }

    return {
      id: message.id,
      role: "user",
      createdAt,
      content: userContent,
      attachments: [],
      metadata: {
        custom: {
          branchId,
        },
      },
    };
  }

  if (normalizedRole !== "assistant") {
    return null;
  }

  const content: ThreadAssistantMessagePart[] = [];
  for (const [index, part] of message.content.entries()) {
    if (!isJsonRecord(part)) continue;
    if (part.type === "text" && typeof part.text === "string") {
      content.push({ type: "text", text: part.text });
      continue;
    }
    if (part.type === "tool-call") {
      const toolCallId =
        getString(part.tool_call_id) ??
        getString(part.toolCallId) ??
        `${message.id}-tool-${index}`;
      const args = isJsonRecord(part.args) ? part.args : {};
      const interruptPayload = interruptByToolId.get(toolCallId);

      content.push({
        type: "tool-call",
        toolCallId,
        toolName: getString(part.name) ?? getString(part.toolName) ?? "tool",
        args,
        argsText: JSON.stringify(args),
        ...(part.result !== undefined ? { result: part.result } : {}),
        ...(interruptPayload
          ? { interrupt: { type: "human", payload: interruptPayload } }
          : {}),
      });
    }
  }

  const safeContent =
    content.length > 0 ? content : [{ type: "text" as const, text: "" }];

  return {
    id: message.id,
    role: "assistant",
    createdAt,
    content: safeContent,
    status: mapAssistantStatus(message),
    metadata: {
      unstable_state: null,
      unstable_annotations: [],
      unstable_data: [],
      steps: [],
      custom: {
        branchId,
      },
    },
  };
};

const toMessageRepository = (
  state: BackendThreadState,
): ExportedMessageRepository => {
  const interruptByToolId = new Map<string, JsonRecord>();
  for (const interrupt of state.interrupts) {
    const toolCallId = getString(interrupt.tool_call_id);
    if (toolCallId) {
      interruptByToolId.set(toolCallId, interrupt);
    }
  }

  const messages: ExportedMessageRepository["messages"] = [];
  const includedIds = new Set<string>();
  let lastIncludedId: string | null = null;

  for (const record of state.messages) {
    const threadMessage = toThreadMessage(record, interruptByToolId);
    if (!threadMessage) continue;

    const recordParent =
      typeof record.parent_id === "string" ? record.parent_id : null;
    const parentId =
      recordParent && includedIds.has(recordParent)
        ? recordParent
        : lastIncludedId;

    messages.push({
      parentId,
      message: threadMessage,
    });
    includedIds.add(threadMessage.id);
    lastIncludedId = threadMessage.id;
  }

  const headId =
    state.head_id && includedIds.has(state.head_id) ? state.head_id : lastIncludedId;
  return {
    headId,
    messages,
  };
};

const branchIdForParent = (
  state: BackendThreadState,
  parentId: string | null,
): string | null => {
  if (!parentId) return null;
  const parent = state.messages.find((message) => message.id === parentId);
  if (!parent || typeof parent.branch_id !== "string") {
    return null;
  }
  return parent.branch_id;
};

const toCommandMessage = (
  message: AppendMessage,
  branchId?: string | null,
): AssistantMessagePayload => {
  const parts: Array<Record<string, unknown>> = [];
  for (const part of message.content) {
    if (part.type === "text") {
      parts.push({ type: "text", text: part.text });
      continue;
    }
    if (part.type === "image" && typeof part.image === "string") {
      parts.push({ type: "image", image: part.image });
    }
  }

  return {
    id: crypto.randomUUID(),
    role: "user",
    parent_id: message.parentId,
    ...(branchId ? { branch_id: branchId } : {}),
    parts: parts.length > 0 ? parts : [{ type: "text", text: "" }],
  };
};

const toOptimisticBackendMessage = (
  payload: AssistantMessagePayload,
): BackendMessage => {
  return {
    id: payload.id ?? crypto.randomUUID(),
    role: "human",
    content: (payload.parts ?? payload.content ?? []) as Array<Record<string, unknown>>,
    ...(payload.parent_id ? { parent_id: payload.parent_id } : {}),
    ...(payload.branch_id ? { branch_id: payload.branch_id } : {}),
    created_at: toEpochSeconds(),
  };
};

const savePendingWelcomeMessage = (
  threadId: string,
  message: AssistantMessagePayload,
) => {
  if (typeof window === "undefined") return;
  const payload: PendingWelcomeMessage = {
    threadId,
    message,
  };
  window.sessionStorage.setItem(
    PENDING_WELCOME_MESSAGE_KEY,
    JSON.stringify(payload),
  );
};

const consumePendingWelcomeMessage = (
  threadId: string,
): AssistantMessagePayload | null => {
  if (typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(PENDING_WELCOME_MESSAGE_KEY);
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as PendingWelcomeMessage;
    if (parsed.threadId !== threadId) {
      return null;
    }
    window.sessionStorage.removeItem(PENDING_WELCOME_MESSAGE_KEY);
    return parsed.message;
  } catch {
    window.sessionStorage.removeItem(PENDING_WELCOME_MESSAGE_KEY);
    return null;
  }
};

export const useWeatherAssistantRuntime = (threadId: string | null) => {
  const router = useRouter();
  const abortRef = useRef<AbortController | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isLoading, setIsLoading] = useState(() => threadId !== null);
  const [backendState, setBackendState] = useState<BackendThreadState>(() =>
    createDraftState(threadId),
  );

  useEffect(() => {
    let ignore = false;

    if (!threadId) {
      setBackendState(createDraftState(null));
      setIsLoading(false);
      setIsRunning(false);
      return;
    }

    setIsLoading(true);
    void getThreadState(threadId)
      .then((response) => {
        if (ignore) return;
        setBackendState(
          normalizeBackendState(
            response.state,
            response.thread_id,
            response.title,
            response.status,
          ),
        );
      })
      .catch((error) => {
        if (ignore) return;
        console.error("Failed to load thread state:", error);
        setBackendState(createDraftState(threadId));
      })
      .finally(() => {
        if (!ignore) {
          setIsLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [threadId]);

  const runCommands = useCallback(
    async (activeThreadId: string, commands: AssistantCommandPayload[]) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setIsRunning(true);

      try {
        await sendAssistantCommands(
          {
            thread_id: activeThreadId,
            commands,
          },
          {
            signal: controller.signal,
            onOperation: (operation) => {
              setBackendState((previous) => applyOperation(previous, operation));
            },
          },
        );
      } catch (error) {
        if (
          !(error instanceof DOMException && error.name === "AbortError")
        ) {
          console.error("Assistant command stream failed:", error);
        }
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
        setIsRunning(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!threadId || isLoading) return;
    const pendingMessage = consumePendingWelcomeMessage(threadId);
    if (!pendingMessage) return;

    const optimisticMessage = toOptimisticBackendMessage(pendingMessage);
    setBackendState((previous) => {
      const exists = previous.messages.some(
        (entry) => entry.id === optimisticMessage.id,
      );
      if (exists) return previous;
      return {
        ...previous,
        messages: [...previous.messages, optimisticMessage],
        head_id: optimisticMessage.id,
      };
    });

    void runCommands(threadId, [
      {
        type: "add-message",
        message: pendingMessage,
      },
    ]);
  }, [isLoading, runCommands, threadId]);

  const setMessages = useCallback((messages: readonly ThreadMessage[]) => {
    const headId = messages.at(-1)?.id ?? null;
    setBackendState((previous) => ({
      ...previous,
      head_id: headId,
    }));
  }, []);

  const onNew = useCallback(
    async (message: AppendMessage) => {
      const branchId = branchIdForParent(backendState, message.parentId);
      const payload = toCommandMessage(message, branchId);

      if (!threadId) {
        const created = await createThread();
        savePendingWelcomeMessage(created.thread_id, payload);
        router.push(`/chat/${created.thread_id}`);
        return;
      }

      const optimisticMessage = toOptimisticBackendMessage(payload);
      setBackendState((previous) => {
        const exists = previous.messages.some(
          (entry) => entry.id === optimisticMessage.id,
        );
        if (exists) return previous;
        return {
          ...previous,
          messages: [...previous.messages, optimisticMessage],
          head_id: optimisticMessage.id,
        };
      });

      await runCommands(threadId, [
        {
          type: "add-message",
          message: payload,
        },
      ]);
    },
    [backendState, router, runCommands, threadId],
  );

  const onEdit = useCallback(
    async (message: AppendMessage) => {
      if (!threadId) return;
      const branchId = branchIdForParent(backendState, message.parentId);
      await runCommands(threadId, [
        {
          type: "add-message",
          message: toCommandMessage(message, branchId),
        },
      ]);
    },
    [backendState, runCommands, threadId],
  );

  const onReload = useCallback(
    async (parentId: string | null) => {
      if (!threadId) return;
      const branchId = branchIdForParent(backendState, parentId);
      await runCommands(threadId, [
        {
          type: "regenerate",
          parentId,
          ...(branchId ? { branchId } : {}),
        },
      ]);
    },
    [backendState, runCommands, threadId],
  );

  const onCancel = useCallback(async () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsRunning(false);
  }, []);

  const onAddToolResult = useCallback(
    async (options: AddToolResultOptions) => {
      if (!threadId) return;
      const resultPayload =
        isJsonRecord(options.result) && options.result !== null
          ? options.result
          : {
              decision: options.isError ? "decline" : "approve",
              value: options.result,
            };

      await runCommands(threadId, [
        {
          type: "add-tool-result",
          toolCallId: options.toolCallId,
          result: resultPayload,
        },
      ]);
    },
    [runCommands, threadId],
  );

  const onResumeToolCall = useCallback(
    (options: { toolCallId: string; payload: unknown }) => {
      if (!threadId) return;
      const resumePayload = isJsonRecord(options.payload)
        ? options.payload
        : { decision: "approve" };
      void runCommands(threadId, [
        {
          type: "resume-tool-call",
          toolCallId: options.toolCallId,
          resume: resumePayload,
        },
      ]);
    },
    [runCommands, threadId],
  );

  const messageRepository = useMemo(() => {
    return toMessageRepository(backendState);
  }, [backendState]);

  return useExternalStoreRuntime({
    messageRepository,
    isLoading,
    isRunning,
    setMessages,
    onNew,
    onEdit,
    onReload,
    onCancel,
    onAddToolResult,
    onResumeToolCall,
    onLoadExternalState: (state) => {
      if (!threadId) return;
      setBackendState(normalizeBackendState(state, threadId, null, "regular"));
    },
  });
};
