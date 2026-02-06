"use client";

import { MyRuntimeProvider } from "@/components/assistant-ui/MyRuntimeProvider";
import { Thread } from "@/components/assistant-ui/thread";

export const Assistant = () => {
  return (
    <MyRuntimeProvider>
      <div className="relative flex h-dvh flex-col">
        <div className="flex-1 overflow-hidden">
          <Thread />
        </div>
      </div>
    </MyRuntimeProvider>
  );
};
