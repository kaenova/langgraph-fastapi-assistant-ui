"use client";

import { Thread } from "@/components/assistant-ui/thread";
import {
  MyRuntimeProvider,
  HitlApprovalBanner,
} from "@/components/MyRuntimeProvider";

export const Assistant = () => {
  return (
    <MyRuntimeProvider>
      <div className="relative flex h-dvh flex-col">
        <div className="flex-1 overflow-hidden">
          <Thread />
        </div>
        <HitlApprovalBanner />
      </div>
    </MyRuntimeProvider>
  );
};
