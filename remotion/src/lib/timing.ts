import {interpolate, useCurrentFrame, useVideoConfig, Easing} from 'remotion';

/**
 * Clip timing, expressed once so no composition can get it wrong.
 *
 * The old graphics froze because nothing tied the animation to the clip length.
 * Measured: a 2.6s stats card whose last motion was at 0.52s, a 2.6s headline
 * that stopped at 0.72s — 80% and 72% of their screen time was a still image.
 * A prompt asking for "motion throughout" is a request; this is a constraint.
 *
 * Three phases, as fractions of the clip:
 *   ENTER  0.00-0.12   the frame arrives
 *   BUILD  0.12-0.72   content assembles, staggered
 *   SETTLE 0.72-1.00   the reader reads, and the frame keeps breathing
 *
 * SETTLE is deliberately not "hold". A viewer needs dwell time to read a
 * headline, so the content must stop moving — but the FRAME must not. `drift`
 * gives every composition a continuous sub-perceptual push through settle, so
 * the clip is alive while the words stay still long enough to read.
 */
// enter is 0.05, not 0.12. A clip is CUT TO, so its first frame is the first
// thing the viewer sees: with a 12% lead-in a 2.6s card showed an empty
// background for its first ~0.3s, which reads as a black flash on the cut
// rather than as an entrance. Sampled at t=4.0s in a real build, the panel was
// fully black between the previous clip and a quote card 0.1s into its life.
// build ends at 45%, not 72%.
//
// The old split left a 2.6s card complete for only its final 0.73 SECONDS —
// measured across a real build, every short clip in the video. Nobody reads a
// quote in 0.73s. The build phase is not reading time: text is still arriving,
// moving and incomplete. Only the settle phase is legible, so the settle has to
// be the MAJORITY of the clip, not a quarter of it.
export const PHASE = {enter: 0.05, build: 0.45} as const;

export const useClip = () => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps, width, height} = useVideoConfig();
  const t = durationInFrames <= 1 ? 1 : frame / (durationInFrames - 1);
  return {frame, t, durationInFrames, fps, width, height};
};

/** Eased 0->1 across an arbitrary window of the clip, clamped outside it. */
export const at = (t: number, from: number, to: number, easing = Easing.out(Easing.cubic)) =>
  interpolate(t, [from, to], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing,
  });

/**
 * Stagger `count` items across the BUILD phase.
 *
 * Returns each item's own 0->1 progress. Items overlap slightly so the build
 * reads as one movement rather than a queue of separate arrivals.
 */
export const stagger = (t: number, i: number, count: number, opts?: {from?: number; to?: number}) => {
  const from = opts?.from ?? PHASE.enter;
  const to = opts?.to ?? PHASE.build;
  const n = Math.max(1, count);
  const slot = (to - from) / n;
  const start = from + slot * i;
  // 1.8 slots of overlap keeps the cadence continuous instead of stepped.
  return at(t, start, Math.min(to, start + slot * 1.8));
};

/**
 * The continuous push that keeps a settled frame from reading as a freeze.
 * ~2.5% over the clip: below conscious notice, above a still image.
 */
export const drift = (t: number, amount = 0.025) => 1 + amount * t;

/** A cursor that blinks for the whole clip — motion of last resort. */
export const blink = (frame: number, fps: number) =>
  Math.floor(frame / Math.max(1, Math.round(fps * 0.45))) % 2 === 0 ? 1 : 0.15;
