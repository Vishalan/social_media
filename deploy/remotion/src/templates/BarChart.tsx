/**
 * BarChart composition — N labeled bars animate from zero height up to their
 * final value. Labels render in white on a navy matte, bars in sky blue, all
 * per the CommonCreed brand palette.
 *
 * Props are validated at the server layer; this component trusts its inputs.
 */
import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from "remotion";

import { BRAND_FONT_FAMILY, NAVY, SKY_BLUE, WHITE } from "../branding.js";

export interface BarDatum {
  label: string;
  value: number;
}

export interface BarChartProps {
  title?: string;
  bars: BarDatum[];
  /** Value displayed on the y-axis top; falls back to max(bars). */
  yMax?: number;
}

/**
 * Default props used when the composition is opened in Remotion Studio without
 * explicit inputProps. The production server always passes inputProps.
 */
export const barChartDefaultProps: BarChartProps = {
  title: "CommonCreed",
  bars: [
    { label: "Mon", value: 12 },
    { label: "Tue", value: 19 },
    { label: "Wed", value: 8 },
    { label: "Thu", value: 24 },
    { label: "Fri", value: 17 },
  ],
};

/**
 * Eased 0 -> 1 progression over the entire composition. We use this to drive
 * every bar simultaneously — staggered entrances add complexity without
 * meaningfully improving the "watch number go up" visual the engagement layer
 * cares about.
 */
function useGrowProgress(): number {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return interpolate(frame, [0, Math.max(durationInFrames - 1, 1)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
}

export const BarChart: React.FC<BarChartProps> = ({ title, bars, yMax }) => {
  const progress = useGrowProgress();
  const { width, height } = useVideoConfig();

  const effectiveMax =
    yMax ?? Math.max(1, ...bars.map((b) => b.value));

  // Layout: title on top, chart area below. All sizing is relative so the
  // same composition works at 1080x1920 (shorts) or 1920x1080 (landscape).
  const titleHeight = title ? height * 0.12 : 0;
  const chartTop = titleHeight + height * 0.04;
  const chartBottom = height * 0.88;
  const chartHeight = chartBottom - chartTop;
  const chartLeft = width * 0.08;
  const chartRight = width * 0.92;
  const chartWidth = chartRight - chartLeft;

  const gap = chartWidth * 0.04;
  const totalGap = gap * (bars.length + 1);
  const barWidth = Math.max(1, (chartWidth - totalGap) / bars.length);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: NAVY,
        fontFamily: BRAND_FONT_FAMILY,
        color: WHITE,
      }}
    >
      {title ? (
        <div
          style={{
            position: "absolute",
            top: height * 0.04,
            left: 0,
            width: "100%",
            textAlign: "center",
            fontSize: Math.round(height * 0.055),
            fontWeight: 700,
            letterSpacing: "-0.02em",
          }}
        >
          {title}
        </div>
      ) : null}

      {bars.map((bar, i) => {
        const finalHeight = (bar.value / effectiveMax) * chartHeight * 0.9;
        const currentHeight = finalHeight * progress;
        const x = chartLeft + gap + i * (barWidth + gap);
        const y = chartBottom - currentHeight;

        return (
          <React.Fragment key={`${bar.label}-${i}`}>
            <div
              style={{
                position: "absolute",
                left: x,
                top: y,
                width: barWidth,
                height: currentHeight,
                backgroundColor: SKY_BLUE,
                borderRadius: 8,
              }}
            />
            <div
              style={{
                position: "absolute",
                left: x,
                top: chartBottom + height * 0.01,
                width: barWidth,
                textAlign: "center",
                fontSize: Math.round(height * 0.028),
                fontWeight: 600,
                color: WHITE,
              }}
            >
              {bar.label}
            </div>
            <div
              style={{
                position: "absolute",
                left: x,
                top: y - height * 0.04,
                width: barWidth,
                textAlign: "center",
                fontSize: Math.round(height * 0.03),
                fontWeight: 700,
                color: SKY_BLUE,
                opacity: progress,
              }}
            >
              {Math.round(bar.value * progress).toLocaleString()}
            </div>
          </React.Fragment>
        );
      })}
    </AbsoluteFill>
  );
};
