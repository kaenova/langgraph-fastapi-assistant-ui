type UnknownRecord = Record<string, unknown>;

function asRecord(value: unknown): UnknownRecord | null {
  return value && typeof value === "object" ? (value as UnknownRecord) : null;
}

function getCustomMetadata(message: unknown): UnknownRecord {
  const messageRecord = asRecord(message);
  const metadata = asRecord(messageRecord?.metadata);
  const custom = asRecord(metadata?.custom);
  return custom ?? {};
}

export function hasNextShouldCompactFlag(message: unknown): boolean {
  return getCustomMetadata(message).next_should_compact === true;
}

export function isCompactionMarkerMessage(message: unknown): boolean {
  return getCustomMetadata(message).compaction === true;
}

export function sliceMessagesFromLatestCompaction<T>(messages: readonly T[]): T[] {
  let markerIndex = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (isCompactionMarkerMessage(messages[index])) {
      markerIndex = index;
      break;
    }
  }
  if (markerIndex < 0) {
    return [...messages];
  }
  return messages.slice(markerIndex);
}

export function toAssistantCustomMetadata(
  metadata: unknown,
): { custom: Record<string, unknown> } {
  return {
    custom: getCustomMetadata({ metadata }),
  };
}
