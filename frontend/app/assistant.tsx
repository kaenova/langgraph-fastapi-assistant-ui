"use client";

import { CustomLanggraphRuntime } from "@/components/assistant-ui/CustomLanggraphRuntime";
import { Thread } from "@/components/assistant-ui/thread";
import type { ReactNode } from "react";

export const Assistant = ({
  threadId,
  children,
}: {
  threadId?: string;
  children?: ReactNode;
}) => {
  return (
    <CustomLanggraphRuntime threadId={threadId}>
      <div className="relative flex h-dvh flex-col">
        <div className="flex-1 overflow-hidden">
          {children}
          <Thread showWelcome={false} />
        </div>
      </div>
    </CustomLanggraphRuntime>
  );
};
