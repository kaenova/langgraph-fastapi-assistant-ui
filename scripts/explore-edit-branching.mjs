import { Readable } from "node:stream";
import { WritableStream } from "node:stream/web";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const { MessageRepository } = await import(
  "../frontend/node_modules/@assistant-ui/react/dist/legacy-runtime/runtime-cores/utils/MessageRepository.js"
);
const { fromThreadMessageLike } = await import(
  "../frontend/node_modules/@assistant-ui/react/dist/legacy-runtime/runtime-cores/external-store/ThreadMessageLike.js"
);

const makeMessage = (id, role, text, overrides = {}) =>
  fromThreadMessageLike(
    {
      id,
      role,
      content: [{ type: "text", text }],
      ...overrides,
    },
    id,
    { type: "complete", reason: "stop" },
  );

const repo = new MessageRepository();
const user1 = makeMessage("u1", "user", "First message");
const assistant1 = makeMessage("a1", "assistant", "Initial reply", {
  metadata: { unstable_state: { version: 1 } },
});
const user2 = makeMessage("u2", "user", "Second message");

repo.addOrUpdateMessage(null, user1);
repo.addOrUpdateMessage("u1", assistant1);
repo.addOrUpdateMessage("a1", user2);

const branchReply = makeMessage("a1b", "assistant", "Branch reply", {
  metadata: { unstable_state: { version: 2 } },
});
repo.addOrUpdateMessage("u1", branchReply);

const toBrief = (message) => {
  const text = message.content
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("");
  return { id: message.id, role: message.role, text };
};

const report = {
  branchesAtUser1: repo.getBranches("a1"),
  headId: repo.headId,
  currentBranch: repo.getMessages().map(toBrief),
};

repo.switchToBranch("a1b");
report.afterSwitch = {
  headId: repo.headId,
  currentBranch: repo.getMessages().map(toBrief),
};

const exportState = repo.export();
const repo2 = new MessageRepository();
repo2.import(exportState);
report.reimported = {
  headId: repo2.headId,
  currentBranch: repo2.getMessages().map(toBrief),
};

console.log(JSON.stringify(report, null, 2));
