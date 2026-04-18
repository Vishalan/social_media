/**
 * NumberTicker composition — one number animates from `start` to `end`,
 * eased over the composition duration. Optional prefix (e.g. "$") and
 * suffix (e.g. "%", " users") render alongside.
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

export interface NumberTickerProps {
  start: number;
  end: number;
  /** Decimal places to render on the animated number. Defaults to 0. */
  decimals?: number;
  prefix?: string;
  suffix?: string;
  /** Caption rendered above the number (e.g. "Monthly revenue"). */
  caption?: string;
}

export const numberTickerDefaultProps: NumberTickerProps = {
  start: 0,
  end: 10000,
  decimals: 0,
  prefix: "",
  suffix: "",
  caption: "Monthly reach",
};

function formatValue(value: number, decimals: number): string {
  if (decimals <= 0) {
    return Math.round(value).toLocaleString();
  }
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export const NumberTicker: React.FC<NumberTickerProps> = ({
  start,
  end,
  decimals = 0,
  prefix = "",
  suffix = "",
  caption,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, height } = useVideoConfig();

  const progress = interpolate(
    frame,
    [0, Math.max(durationInFrames - 1, 1)],
    [0, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    },
  );

  const current = start + (end - start) * progress;
  const formatted = `${prefix}${formatValue(current, decimals)}${suffix}`;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: NAVY,
        fontFamily: BRAND_FONT_FAMILY,
        color: WHITE,
        justifyContent: "center",
        alignItems: "center",
        textAlign: "center",
      }}
    >
      {caption ? (
        <div
          style={{
            fontSize: Math.round(height * 0.045),
            fontWeight: 600,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            color: WHITE,
            opacity: 0.85,
            marginBottom: height * 0.02,
          }}
        >
          {caption}
        </div>
      ) : null}
      <div
        style={{
          fontSize: Math.round(height * 0.18),
          fontWeight: 800,
          color: SKY_BLUE,
          lineHeight: 1,
          fontVariantNumeric: "tabular-nums",
          letterSpacing: "-0.03em",
        }}
      >
        {formatted}
      </div>
    </AbsoluteFill>
  );
};
