import {spring, interpolate, Easing} from 'remotion';

/**
 * Motion vocabulary shared by every composition.
 *
 * The first build used Easing.out(Easing.cubic) everywhere. It is inoffensive
 * and it is why the graphics read as functional rather than designed: cubic
 * decelerates evenly, so nothing has weight and nothing arrives. The Remotion
 * showcase work leans on two things instead — spring physics for anything that
 * ENTERS, and expo-out for anything that TRAVELS — and that difference is most
 * of the perceived quality gap.
 */

/** The expo-out curve used across Remotion's own examples. Fast out, long settle. */
export const EXPO = Easing.bezier(0.16, 1, 0.3, 1);

/** A crisp arrival with a touch of overshoot. For cards, chips, badges. */
export const pop = (frame: number, fps: number, delayFrames = 0) =>
  spring({
    frame: frame - delayFrames,
    fps,
    config: {damping: 12, stiffness: 170, mass: 0.9},
  });

/** Heavier arrival for large type: settles rather than bounces. */
export const settle = (frame: number, fps: number, delayFrames = 0) =>
  spring({
    frame: frame - delayFrames,
    fps,
    config: {damping: 18, stiffness: 120, mass: 1.1},
  });

/** Eased 0->1 across a window of normalised clip time. */
export const ramp = (t: number, from: number, to: number) =>
  interpolate(t, [from, to], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: EXPO,
  });

/**
 * A wipe reveal, as a clip-path.
 *
 * Text that fades in reads as a slideshow; text uncovered by a moving edge
 * reads as motion design. Costs nothing extra and changes the character of
 * every line it is applied to.
 */
export const wipe = (p: number, direction: 'up' | 'left' = 'up') =>
  direction === 'up'
    ? `inset(${(1 - p) * 105}% 0% 0% 0%)`
    : `inset(0% ${(1 - p) * 105}% 0% 0%)`;

/** Slight blur on entry, resolving to sharp. Adds depth to an arrival. */
export const focusIn = (p: number, maxBlur = 12) =>
  `blur(${(1 - p) * maxBlur}px)`;

/** Deterministic pseudo-random in [0,1) — for drifting decorative elements. */
export const rand = (seed: number) => {
  const x = Math.sin(seed * 12.9898) * 43758.5453;
  return x - Math.floor(x);
};
