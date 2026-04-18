/**
 * Remotion root — registers every composition this sidecar can render.
 *
 * The server (`server.ts`) bundles this entry point at startup via
 * `@remotion/bundler`, then selects compositions by `id` when a render
 * request comes in. The `id` strings MUST match the `template_id`
 * values the HTTP API accepts (`bar_chart`, `number_ticker`, `line_chart`).
 *
 * Composition dimensions default to 1080x1920 (9:16 vertical) because the
 * engagement layer produces shorts-first content; the server overrides
 * `durationInFrames` per request based on `target_duration_s`.
 */
import React from "react";
import { registerRoot, Composition } from "remotion";

import { BarChart, barChartDefaultProps } from "./templates/BarChart.js";
import { LineChart, lineChartDefaultProps } from "./templates/LineChart.js";
import {
  NumberTicker,
  numberTickerDefaultProps,
} from "./templates/NumberTicker.js";

const WIDTH = 1080;
const HEIGHT = 1920;
const FPS = 30;
const DEFAULT_DURATION_FRAMES = 150;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="bar_chart"
        component={BarChart as unknown as React.ComponentType<Record<string, unknown>>}
        durationInFrames={DEFAULT_DURATION_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={barChartDefaultProps as unknown as Record<string, unknown>}
      />
      <Composition
        id="number_ticker"
        component={NumberTicker as unknown as React.ComponentType<Record<string, unknown>>}
        durationInFrames={DEFAULT_DURATION_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={numberTickerDefaultProps as unknown as Record<string, unknown>}
      />
      <Composition
        id="line_chart"
        component={LineChart as unknown as React.ComponentType<Record<string, unknown>>}
        durationInFrames={DEFAULT_DURATION_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={lineChartDefaultProps as unknown as Record<string, unknown>}
      />
    </>
  );
};

registerRoot(RemotionRoot);
