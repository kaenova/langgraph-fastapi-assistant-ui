import type { HistoryRepository, LocalHistoryLoadResult } from "./types";

// Normalizes unknown timestamp input into Date to satisfy runtime expectations.
function toDateOrNow(value: unknown): Date {
  if (value instanceof Date) return value;
  if (typeof value === "string" || typeof value === "number") {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) return parsed;
  }
  return new Date();
}

// Reorders and sanitizes stored history so parent-child message links are valid.
export function normalizeHistoryRepository(
  repository: HistoryRepository,
): LocalHistoryLoadResult {
  const normalizedItems = repository.messages.map((item) => ({
    parentId: item.parentId ?? null,
    runConfig: item.runConfig ?? {},
    message: {
      ...item.message,
      createdAt: toDateOrNow(item.message.createdAt),
    },
  }));

  const pending = [...normalizedItems];
  const accepted: LocalHistoryLoadResult["messages"] = [];
  const acceptedIds = new Set<string>();

  while (pending.length > 0) {
    let progressed = false;
    for (let index = 0; index < pending.length; ) {
      const item = pending[index];
      const messageRecord = item.message as Record<string, unknown>;
      const messageId =
        typeof messageRecord.id === "string" ? messageRecord.id : undefined;
      if (!messageId) {
        pending.splice(index, 1);
        progressed = true;
        continue;
      }

      if (item.parentId === null || acceptedIds.has(item.parentId)) {
        accepted.push(item as LocalHistoryLoadResult["messages"][number]);
        acceptedIds.add(messageId);
        pending.splice(index, 1);
        progressed = true;
        continue;
      }

      index += 1;
    }

    if (!progressed) {
      break;
    }
  }

  const fallbackHeadId =
    accepted.length > 0
      ? (((accepted[accepted.length - 1].message as Record<string, unknown>)
          .id as string | undefined) ?? null)
      : null;
  const resolvedHeadId =
    repository.headId && acceptedIds.has(repository.headId)
      ? repository.headId
      : fallbackHeadId;

  return {
    headId: resolvedHeadId,
    messages: accepted,
  };
}
