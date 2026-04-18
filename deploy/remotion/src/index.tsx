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

import {
  BarChart,
  barChartDefaultProps,
  type BarChartProps,
} from "./templates/BarChart.js";
import {
  LineChart,
  lineChartDefaultProps,
  type LineChartProps,
} from "./templates/LineChart.js";
import {
  NumberTicker,
  numberTickerDefaultProps,
  type NumberTickerProps,
} from "./templates/NumberTicker.js";

/** Vertical 9:16 canvas shared by every template. */
const WIDTH = 1080;
const HEIGHT = 1920;
const FPS = 30;
/** Placeholder; server overrides per-request. */
const DEFAULT_DURATION_FRAMES = 150;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition<typeof barChartDefaultProps, BarChartProps>
        id="bar_chart"
        component={BarChart}
        durationInFrames={DEFAULT_DURATION_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={barChartDefaultProps}
      />
      <Composition<typeof numberTickerDefaultProps, NumberTickerProps>
        id="number_ticker"
        component={NumberTicker}
        durationInFrames={DEFAULT_DURATION_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={numberTickerDefaultProps}
      />
      <Composition<typeof lineChartDefaultProps, LineChartProps>
        id="line_chart"
        component={LineChart}
        durationInFrames={DEFAULT_DURATION_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={lineChartDefaultProps}
      />
    </>
  );
};

registerRoot(RemotionRoot);
