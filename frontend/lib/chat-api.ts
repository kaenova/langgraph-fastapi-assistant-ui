export type JsonPath = Array<string | number>;

export type StreamOperation =
  | {
      type: "set";
      path: JsonPath;
      value: unknown;
    }
  | {
      type: "append-text";
      path: JsonPath;
      value: string;
    };

export interface ThreadMetadata {
  thread_id: string;
  status: string;
  title: string | null;
  created_at: number;
  updated_at: number;
}

export interface ThreadStateResponse extends ThreadMetadata {
  state: Record<string, unknown>;
}

export interface AssistantMessagePayload {
  id?: string;
  role?: string;
  parts?: Array<Record<string, unknown>>;
  content?: Array<Record<string, unknown>>;
  parent_id?: string | null;
  branch_id?: string | null;
}

export interface AssistantCommandPayload {
  type: string;
  message?: AssistantMessagePayload;
  toolCallId?: string;
  result?: Record<string, unknown>;
  resume?: Record<string, unknown>;
  decision?: string;
  args?: Record<string, unknown>;
  parentId?: string | null;
  messageId?: string | null;
  branchId?: string | null;
}

export interface AssistantBatchPayload {
  thread_id: string;
  commands: AssistantCommandPayload[];
}

const API_BASE = "/api/be/api/v1";

const readErrorBody = async (response: Response): Promise<string> => {
  try {
    return await response.text();
  } catch {
    return "";
  }
};

const expectJson = async <T>(response: Response): Promise<T> => {
  if (!response.ok) {
    const body = await readErrorBody(response);
    throw new Error(`Request failed (${response.status}): ${body}`);
  }
  return (await response.json()) as T;
};

export const createThread = async (
  title?: string,
): Promise<ThreadMetadata> => {
  const response = await fetch(`${API_BASE}/threads`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ...(title ? { title } : {}),
    }),
  });
  return expectJson<ThreadMetadata>(response);
};

export const getThreadState = async (
  threadId: string,
): Promise<ThreadStateResponse> => {
  const response = await fetch(`${API_BASE}/threads/${threadId}/state`, {
    method: "GET",
  });
  return expectJson<ThreadStateResponse>(response);
};

const parseOperation = (line: string): StreamOperation | null => {
  if (!line.trim()) return null;
  const parsed = JSON.parse(line) as StreamOperation;
  if (parsed.type === "set" || parsed.type === "append-text") {
    return parsed;
  }
  return null;
};

interface StreamOptions {
  signal?: AbortSignal;
  onOperation: (operation: StreamOperation) => void;
}

export const sendAssistantCommands = async (
  payload: AssistantBatchPayload,
  options: StreamOptions,
): Promise<void> => {
  const response = await fetch(`${API_BASE}/assistant`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal: options.signal,
  });

  if (!response.ok) {
    const body = await readErrorBody(response);
    throw new Error(`Assistant request failed (${response.status}): ${body}`);
  }

  if (!response.body) {
    throw new Error("Assistant response body is empty");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const operation = parseOperation(line);
      if (operation) {
        options.onOperation(operation);
      }
    }
  }

  const trailing = decoder.decode();
  const finalChunk = `${buffer}${trailing}`.trim();
  if (finalChunk) {
    const operation = parseOperation(finalChunk);
    if (operation) {
      options.onOperation(operation);
    }
  }
};
