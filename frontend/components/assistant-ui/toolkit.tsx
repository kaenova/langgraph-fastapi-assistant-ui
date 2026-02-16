"use client";

import type { Toolkit } from "@assistant-ui/react";
import { z } from "zod";

import { CurrentWeatherToolCard } from "@/components/assistant-ui/tools/current-weather";

/**
 * UI-only toolkit for tools executed on the backend.
 *
 * - Tool names MUST match the backend tool names exactly.
 * - Omit `execute` so assistant-ui treats these as UI-only.
 */
export const appToolkit: Toolkit = {
  current_weather: {
    description: "Check the current weather for a city (HITL approval required).",
    parameters: z.object({
      city: z.string().min(1).describe("City to check"),
    }),
    render: (props) => <CurrentWeatherToolCard {...props} />,
  },
};
