"use client";

import { CustomLanggraphRuntime } from "@/components/assistant-ui/CustomLanggraphRuntime";
import { Thread } from "@/components/assistant-ui/thread";

export const Assistant = () => {
  return (
    <CustomLanggraphRuntime>
      <div className="relative flex h-dvh flex-col">
        <div className="flex-1 overflow-hidden">
          <Thread />
        </div>
      </div>
    </CustomLanggraphRuntime>
  );
};
