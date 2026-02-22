import {
  useLocalRuntime,
  type ChatModelAdapter,
  type ThreadHistoryAdapter,
} from "@assistant-ui/react";
import { useMemo } from "react";

import { visionImageAttachmentAdapter } from "@/lib/vision-attachment-adapter";

type UseTemplateLocalRuntimeOptions = {
  modelAdapter: ChatModelAdapter;
  historyAdapter?: ThreadHistoryAdapter;
};

// Creates a local runtime with shared attachment support and optional history.
export function useTemplateLocalRuntime({
  modelAdapter,
  historyAdapter,
}: UseTemplateLocalRuntimeOptions) {
  const adapters = useMemo(
    () =>
      historyAdapter
        ? {
            history: historyAdapter,
            attachments: visionImageAttachmentAdapter,
          }
        : {
            attachments: visionImageAttachmentAdapter,
          },
    [historyAdapter],
  );

  return useLocalRuntime(modelAdapter, {
    adapters,
    unstable_humanToolNames: ["weather"],
  });
}
