import type { BackendEvent } from "./types";

// Parses newline-delimited JSON chunks from non-SSE streaming responses.
async function* parseNdjsonStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<BackendEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      yield JSON.parse(trimmed) as BackendEvent;
    }
  }

  if (buffer.trim()) {
    yield JSON.parse(buffer.trim()) as BackendEvent;
  }
}

// Parses Server-Sent Events data frames into backend event payloads.
async function* parseSseStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<BackendEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let dataLines: string[] = [];

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const rawLine of lines) {
      const line = rawLine.replace(/\r$/, "");
      if (!line) {
        if (dataLines.length > 0) {
          const payload = dataLines.join("\n");
          dataLines = [];
          if (payload.trim()) {
            yield JSON.parse(payload) as BackendEvent;
          }
        }
        continue;
      }
      if (line.startsWith(":")) continue;
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
  }

  if (buffer.trim()) {
    const line = buffer.replace(/\r$/, "");
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (dataLines.length > 0) {
    const payload = dataLines.join("\n");
    if (payload.trim()) {
      yield JSON.parse(payload) as BackendEvent;
    }
  }
}

// Detects stream format by content-type and delegates to the matching parser.
export async function* parseBackendStream(
  response: Response,
): AsyncGenerator<BackendEvent> {
  if (!response.body) return;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream")) {
    yield* parseSseStream(response.body);
    return;
  }
  yield* parseNdjsonStream(response.body);
}
