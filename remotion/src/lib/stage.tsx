import React from 'react';
import {AbsoluteFill, Easing, interpolate} from 'remotion';

/**
 * A world the camera flies over, instead of elements flying into a frame.
 *
 * Every composition built before this one animated ITS CONTENTS: words slid up,
 * cards faded, bars grew, all inside a frame that never moved. That is the
 * grammar of a slide deck, and it is why the b-roll kept reading as "text and
 * design" no matter how much polish went onto the individual elements — polish
 * cannot turn a slide into a shot.
 *
 * The architecture here is taken from snapcn's terminal-simulator, whose one
 * good idea is worth more than its 891 lines: the scene is a single static
 * world, laid out in its own coordinate space and larger than the frame, and
 * the CAMERA moves between fixed stations within it. Nothing enters from a
 * screen edge because there are no screen edges in the world — there is only
 * where the camera happens to be pointing.
 *
 * Timing constants come from video-shotcraft's shot cards (Apache-2.0), which
 * document each move with measured frame counts, easing and failure modes. Its
 * numbers are quoted at the call sites below, because the numbers ARE the
 * technique: a crash zoom over 6 frames is an impact and the same move over 12
 * is an ordinary push-in.
 */

export type Stop = {
  /** Frame this stop is reached. */
  frame: number;
  /** World point the camera centres on. */
  x: number;
  y: number;
  /** Zoom. 1 = world pixels are frame pixels. */
  z: number;
  /** Dutch angle in degrees. */
  rot?: number;
  /** How the camera ARRIVES here from the previous stop. */
  ease?: 'in' | 'out' | 'inout' | 'linear';
};

export type CameraState = {x: number; y: number; z: number; rot: number};

const CURVES = {
  in: Easing.in(Easing.quad),
  out: Easing.out(Easing.cubic),
  inout: Easing.inOut(Easing.cubic),
  linear: Easing.linear,
} as const;

/**
 * Where the camera is on a given frame.
 *
 * Piecewise: before the first stop it sits on the first, after the last it sits
 * on the last, and between two stops it interpolates on the ARRIVING stop's
 * curve. Holding still outside the declared range is the point — shotcraft's
 * rest rule (R1) is that a move must be followed by at least 30 frames of true
 * stillness, and a camera that keeps drifting because a curve ran off the end
 * never gives the eye the beat it needs to read what it was shown.
 */
export function cameraAt(frame: number, stops: Stop[]): CameraState {
  if (stops.length === 0) return {x: 0, y: 0, z: 1, rot: 0};
  const first = stops[0];
  if (frame <= first.frame) {
    return {x: first.x, y: first.y, z: first.z, rot: first.rot ?? 0};
  }
  for (let i = 1; i < stops.length; i++) {
    const a = stops[i - 1];
    const b = stops[i];
    if (frame <= b.frame) {
      const easing = CURVES[b.ease ?? 'inout'];
      const lerp = (u: number, v: number) =>
        interpolate(frame, [a.frame, b.frame], [u, v], {
          easing,
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
      return {
        x: lerp(a.x, b.x),
        y: lerp(a.y, b.y),
        z: lerp(a.z, b.z),
        rot: lerp(a.rot ?? 0, b.rot ?? 0),
      };
    }
  }
  const last = stops[stops.length - 1];
  return {x: last.x, y: last.y, z: last.z, rot: last.rot ?? 0};
}

/** How far the camera travelled into this frame, in frame-space pixels. */
export function cameraSpeed(frame: number, stops: Stop[]): number {
  const a = cameraAt(frame - 1, stops);
  const b = cameraAt(frame, stops);
  return Math.hypot((b.x - a.x) * b.z, (b.y - a.y) * b.z) + Math.abs(b.z - a.z) * 900;
}

/**
 * Place the world so the camera's focus point lands at frame centre.
 *
 * The whole camera is this one line: translate the world by however much is
 * needed to bring (x, y) to the middle, having scaled it by z.
 */
function worldTransform(c: CameraState, width: number, height: number): string {
  return (
    `rotate(${c.rot}deg) ` +
    `translate(${width / 2 - c.x * c.z}px, ${height / 2 - c.y * c.z}px) ` +
    `scale(${c.z})`
  );
}

export const World: React.FC<{
  frame: number;
  stops: Stop[];
  width: number;
  height: number;
  /** Draw ghosts of recent camera positions while the camera is moving. */
  trail?: boolean;
  children: React.ReactNode;
}> = ({frame, stops, width, height, trail = true, children}) => {
  const cam = cameraAt(frame, stops);
  const speed = cameraSpeed(frame, stops);

  // Motion blur, done the cheap correct way: draw the same world again at the
  // camera positions it occupied a frame or two ago. It costs one extra render
  // per ghost and it is only alive while the camera is actually moving, so a
  // resting shot stays perfectly crisp — which matters, because these panels
  // exist to be READ.
  const ghosts = trail && speed > 6 ? [1, 2, 3] : [];
  const ghostAlpha = Math.min(0.34, speed / 220);

  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      {ghosts.map((back) => (
        <AbsoluteFill
          key={back}
          style={{
            transform: worldTransform(cameraAt(frame - back, stops), width, height),
            transformOrigin: '0 0',
            opacity: ghostAlpha / back,
            filter: `blur(${back * 0.6}px)`,
          }}
        >
          {children}
        </AbsoluteFill>
      ))}
      <AbsoluteFill
        style={{transform: worldTransform(cam, width, height), transformOrigin: '0 0'}}
      >
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** Absolute placement of an object inside the world. */
export const At: React.FC<{
  x: number;
  y: number;
  /** Parallax coefficient — see multiplane() below. 1 = locked to the world. */
  depth?: number;
  children: React.ReactNode;
}> = ({x, y, children}) => (
  <div style={{position: 'absolute', left: x, top: y, transform: 'translate(-50%, -50%)'}}>
    {children}
  </div>
);

// ─── Shot presets ────────────────────────────────────────────────────────────
//
// Each returns camera stops for a whole clip. The frame counts and ranges are
// shotcraft's measured values, not invented ones, and the comments record what
// goes wrong outside those ranges so the next edit does not quietly undo them.

/**
 * Slow push-in: pressure that builds without the viewer noticing it start.
 *
 * shotcraft: scale 1.00 -> 1.14 on Easing.in(quad). The ACCELERATION is the
 * whole technique — a constant-rate push reads as an ordinary zoom, and going
 * past ~1.2 stops being tension and becomes a plain push-in. Being nearly
 * imperceptible for the first second is the design, not a fault.
 */
export function slowPush(durF: number, x: number, y: number, to = 1.14): Stop[] {
  return [
    {frame: 0, x, y, z: 1.0},
    {frame: durF, x, y, z: to, ease: 'in'},
  ];
}

/**
 * Crash zoom: "look at THIS", in one beat.
 *
 * shotcraft: 6 frames (usable 4-8), ease-in, landing 2.4-2.8x, then a 3-6%
 * overshoot recovery over ~5 frames. Beyond 10 frames the impact is gone and it
 * reads as a normal push. Capped at twice per video by the same source, which
 * the director enforces rather than this function.
 */
export function crashZoom(
  durF: number,
  wide: {x: number; y: number},
  target: {x: number; y: number},
  hold = 30,
  /** Zoom to start on and to land on. */
  zooms: {from?: number; to?: number} = {},
): Stop[] {
  const punchAt = Math.min(hold, Math.max(12, durF * 0.34));
  const open = zooms.from ?? 1.0;
  // Never a constant. shotcraft frames the landing so the subject fills
  // 60-75% of the frame, which is a RATIO — baking in 2.5x assumed a world
  // much larger than the frame, and on a window that already spans the frame
  // it simply cropped both edges off the thing the viewer was meant to read.
  const land = zooms.to ?? 2.5;
  return [
    {frame: 0, x: wide.x, y: wide.y, z: open},
    {frame: punchAt, x: wide.x, y: wide.y, z: open, ease: 'linear'},
    {frame: punchAt + 6, x: target.x, y: target.y, z: land, ease: 'in'},
    // The recovery is what gives the landing weight instead of a dead stop.
    {frame: punchAt + 11, x: target.x, y: target.y, z: land * 0.955, ease: 'out'},
    {frame: durF, x: target.x, y: target.y, z: land * 0.955, ease: 'linear'},
  ];
}

/**
 * Pull back to isolation: "in the end there is only this".
 *
 * shotcraft: scale 2.2 -> 0.62 over 110 frames on Easing.out(cubic), origin
 * locked to the subject. The first ~20 frames still fill the frame with the
 * subject, so no separate opening hold is needed.
 */
export function pullBack(durF: number, x: number, y: number): Stop[] {
  return [
    {frame: 0, x, y, z: 2.2},
    {frame: Math.min(durF, 110), x, y, z: 0.72, ease: 'out'},
    {frame: durF, x, y, z: 0.72, ease: 'linear'},
  ];
}

/**
 * A pan between two stations, with a whip in the middle.
 *
 * The camera creeps first, then accelerates — a constant-rate pan across a gap
 * reads as a scrolling web page, which is precisely the look the page-roll
 * b-roll was retired for.
 */
export function flyBetween(
  durF: number,
  a: {x: number; y: number; z?: number},
  b: {x: number; y: number; z?: number},
): Stop[] {
  const settle = Math.round(durF * 0.30);
  const arrive = Math.round(durF * 0.62);
  return [
    {frame: 0, x: a.x, y: a.y, z: a.z ?? 1},
    // The creep: barely moving, so the whip that follows has something to
    // accelerate away from.
    {frame: settle, x: a.x + 26, y: a.y, z: (a.z ?? 1) * 0.99, ease: 'linear'},
    {frame: arrive, x: b.x, y: b.y, z: b.z ?? 1, ease: 'inout'},
    {frame: durF, x: b.x, y: b.y, z: b.z ?? 1, ease: 'linear'},
  ];
}

/**
 * Parallax depth coefficients for a multiplane shot.
 *
 * shotcraft: three layers at 0.35 / 0.7 / 1.4. The gradient between layers has
 * to be at least 2x or the eye cannot separate them, and the far and near
 * layers need blur and desaturation as depth anchors — without those it reads
 * as loose cards flying around rather than as depth. The middle layer is the
 * one being READ, so it never gets blurred.
 */
export const PLANES = {
  far: {k: 0.35, blur: 2, sat: 0.92, opacity: 0.85},
  mid: {k: 0.7, blur: 0, sat: 1, opacity: 1},
  near: {k: 1.4, blur: 3, sat: 1, opacity: 0.9},
} as const;

export const Plane: React.FC<{
  plane: keyof typeof PLANES;
  drive: number;
  children: React.ReactNode;
}> = ({plane, drive, children}) => {
  const p = PLANES[plane];
  return (
    <AbsoluteFill
      style={{
        transform: `translateX(${-drive * p.k}px)`,
        filter: `blur(${p.blur}px) saturate(${p.sat})`,
        opacity: p.opacity,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};
