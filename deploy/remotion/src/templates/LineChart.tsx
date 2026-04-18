/**
 * LineChart composition — an animated polyline draws from left to right over
 * the composition duration, with axis labels on the baseline. Sky blue line
 * on a navy matte, to match the CommonCreed palette.
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

export interface LinePoint {
  label: string;
  value: number;
}

export interface LineChartProps {
  title?: string;
  points: LinePoint[];
  yMax?: number;
}

export const lineChartDefaultProps: LineChartProps = {
  title: "Growth",
  points: [
    { label: "W1", value: 10 },
    { label: "W2", value: 18 },
    { label: "W3", value: 14 },
    { label: "W4", value: 32 },
    { label: "W5", value: 41 },
    { label: "W6", value: 58 },
  ],
};

interface ChartLayout {
  top: number;
  bottom: number;
  left: number;
  right: number;
  chartWidth: number;
  chartHeight: number;
}

function computeLayout(width: number, height: number, hasTitle: boolean): ChartLayout {
  const titleHeight = hasTitle ? height * 0.12 : 0;
  const top = titleHeight + height * 0.04;
  const bottom = height * 0.86;
  const left = width * 0.08;
  const right = width * 0.92;
  return {
    top,
    bottom,
    left,
    right,
    chartWidth: right - left,
    chartHeight: bottom - top,
  };
}

/**
 * Returns the SVG path string for the polyline up to the given progress
 * (0..1). We truncate at a fractional point rather than using
 * stroke-dashoffset so partially-drawn segments interpolate smoothly.
 */
function buildPathUpTo(
  points: { x: number; y: number }[],
  progress: number,
): string {
  if (points.length === 0 || progress <= 0) return "";

  const total = points.length - 1;
  const target = total * progress;
  const fullSegments = Math.floor(target);
  const partial = target - fullSegments;

  const parts: string[] = [`M ${points[0].x} ${points[0].y}`];
  for (let i = 1; i <= fullSegments; i++) {
    parts.push(`L ${points[i].x} ${points[i].y}`);
  }
  if (fullSegments < total && partial > 0) {
    const a = points[fullSegments];
    const b = points[fullSegments + 1];
    const x = a.x + (b.x - a.x) * partial;
    const y = a.y + (b.y - a.y) * partial;
    parts.push(`L ${x} ${y}`);
  }
  return parts.join(" ");
}

export const LineChart: React.FC<LineChartProps> = ({ title, points, yMax }) => {
  const frame = useCurrentFrame();
  const { durationInFrames, width, height } = useVideoConfig();

  const progress = interpolate(
    frame,
    [0, Math.max(durationInFrames - 1, 1)],
    [0, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.cubic),
    },
  );

  const layout = computeLayout(width, height, Boolean(title));
  const effectiveMax = yMax ?? Math.max(1, ...points.map((p) => p.value));

  // Compute screen-space coordinates for each data point.
  const screenPoints = points.map((p, i) => {
    const x =
      points.length <= 1
        ? layout.left + layout.chartWidth / 2
        : layout.left + (i / (points.length - 1)) * layout.chartWidth;
    const y =
      layout.bottom - (p.value / effectiveMax) * layout.chartHeight * 0.9;
    return { x, y };
  });

  const pathD = buildPathUpTo(screenPoints, progress);

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

      <svg
        width={width}
        height={height}
        style={{ position: "absolute", top: 0, left: 0 }}
      >
        {/* Baseline */}
        <line
          x1={layout.left}
          y1={layout.bottom}
          x2={layout.right}
          y2={layout.bottom}
          stroke={WHITE}
          strokeOpacity={0.3}
          strokeWidth={2}
        />
        {/* Animated polyline */}
        <path
          d={pathD}
          fill="none"
          stroke={SKY_BLUE}
          strokeWidth={Math.max(4, Math.round(height * 0.008))}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>

      {points.map((p, i) => {
        const sp = screenPoints[i];
        // Points appear as they're reached by the line sweep.
        const pointProgress = points.length <= 1 ? 1 : i / (points.length - 1);
        const visible = progress >= pointProgress;
        return (
          <div
            key={`${p.label}-${i}`}
            style={{
              position: "absolute",
              left: sp.x - 80,
              top: layout.bottom + height * 0.015,
              width: 160,
              textAlign: "center",
              fontSize: Math.round(height * 0.028),
              fontWeight: 600,
              color: WHITE,
              opacity: visible ? 1 : 0.3,
            }}
          >
            {p.label}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
