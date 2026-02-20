"use client";

import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { useMemo, useState } from "react";

import { ToolFallback } from "@/components/assistant-ui/tool-fallback";
import { Button } from "@/components/ui/button";

type WeatherArgs = {
  city?: string;
  unit?: string;
};

const safeString = (value: unknown, fallback: string): string => {
  return typeof value === "string" && value.trim() ? value : fallback;
};

export const WeatherTool: ToolCallMessagePartComponent<WeatherArgs, unknown> = ({
  toolName,
  args,
  status,
  result,
  resume,
}) => {
  const defaultCity = useMemo(
    () => safeString(args?.city, "Jakarta"),
    [args?.city],
  );
  const defaultUnit = useMemo(
    () => safeString(args?.unit, "celsius"),
    [args?.unit],
  );
  const [city, setCity] = useState(defaultCity);
  const [unit, setUnit] = useState(defaultUnit);

  const requiresAction = status?.type === "requires-action";

  return (
    <ToolFallback.Root defaultOpen>
      <ToolFallback.Trigger toolName={toolName} status={status} />
      <ToolFallback.Content>
        <ToolFallback.Error status={status} />
        <ToolFallback.Args
          argsText={JSON.stringify(
            {
              city,
              unit,
            },
            null,
            2,
          )}
        />

        {requiresAction ? (
          <div className="flex flex-col gap-3 px-4 pb-2">
            <div className="grid gap-2">
              <label className="text-xs">City</label>
              <input
                value={city}
                onChange={(event) => setCity(event.target.value)}
                className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
              />
            </div>
            <div className="grid gap-2">
              <label className="text-xs">Unit</label>
              <input
                value={unit}
                onChange={(event) => setUnit(event.target.value)}
                className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                onClick={() =>
                  resume({
                    decision: "approve",
                    args: { city, unit },
                  })
                }
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  resume({
                    decision: "change-args",
                    args: { city, unit },
                  })
                }
              >
                Change args
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() =>
                  resume({
                    decision: "decline",
                    args: { city, unit },
                    reason: "Rejected from frontend HITL",
                  })
                }
              >
                Decline
              </Button>
            </div>
          </div>
        ) : null}

        <ToolFallback.Result result={result} />
      </ToolFallback.Content>
    </ToolFallback.Root>
  );
};
