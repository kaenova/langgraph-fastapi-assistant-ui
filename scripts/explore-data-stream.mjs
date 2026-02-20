import { readFile } from "node:fs/promises";
import { WritableStream } from "node:stream/web";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const streamPath = resolve(__dirname, "data-stream.sample.txt");
const streamText = await readFile(streamPath, "utf-8");

const { DataStreamDecoder, AssistantMessageAccumulator } = await import(
  "../frontend/node_modules/assistant-stream/dist/index.js"
);

const encoder = new TextEncoder();
const webReadable = new ReadableStream({
  start(controller) {
    controller.enqueue(encoder.encode(streamText));
    controller.close();
  },
});

const decoder = new DataStreamDecoder();
const accumulator = new AssistantMessageAccumulator({
  throttle: false,
});

const messages = [];
await webReadable
  .pipeThrough(decoder)
  .pipeThrough(accumulator)
  .pipeTo(
    new WritableStream({
      write(message) {
        messages.push(message);
      },
    })
  );

const lastMessage = messages[messages.length - 1];
if (!lastMessage) {
  console.error("No message emitted. Check data-stream.sample.txt content.");
  process.exit(1);
}

const output = {
  finalStatus: lastMessage.status,
  parts: lastMessage.parts,
  metadata: {
    unstable_state: lastMessage.metadata.unstable_state,
    unstable_data: lastMessage.metadata.unstable_data,
    unstable_annotations: lastMessage.metadata.unstable_annotations,
    steps: lastMessage.metadata.steps,
  },
};

console.log(JSON.stringify(output, null, 2));
