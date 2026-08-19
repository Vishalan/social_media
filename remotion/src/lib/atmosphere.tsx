import React from 'react';
import {AbsoluteFill, interpolate} from 'remotion';
import {noise2D} from '@remotion/noise';
import {useClip} from './timing';
import {accentOf, accent2Of, bgOf, Palette} from '../theme';

/**
 * Atmosphere layers, learned from studying well-made Remotion work.
 *
 * Our first backdrop was two radial gradients drifting linearly. It reads as
 * flat because linear drift is the one motion the eye immediately recognises as
 * mechanical. The technique that actually works is ORBITAL: blobs travelling on
 * compound sine paths at different periods, so the field never repeats and no
 * single element looks like it is on a track.
 *
 * Everything here is heavily blurred and low-opacity by design. It is a field
 * for content to sit on, not a thing to look at.
 */
export const Aurora: React.FC<{
  palette: Palette;
  speed?: number;
  opacity?: number;
}> = ({palette, speed = 0.35, opacity = 0.34}) => {
  const {frame, fps, width, height} = useClip();
  const t = (frame / fps) * speed;
  const cols = [accentOf(palette), accent2Of(palette), accentOf(palette)];

  return (
    <AbsoluteFill style={{overflow: 'hidden', opacity}}>
      {cols.map((color, i) => {
        // Compound sine/cosine at different periods: the path never closes, so
        // the motion cannot be read as a loop even over a long clip.
        const a = t + (i * Math.PI * 2) / cols.length;
        const x = 50 + Math.sin(a) * 26 + Math.cos(a * 0.7 + i) * 10;
        const y = 46 + Math.cos(a * 0.8) * 20 + Math.sin(a * 1.3 + i * 2) * 8;
        const sx = 1 + Math.sin(t * 0.5 + i * 1.5) * 0.28;
        const sy = 1 + Math.cos(t * 0.7 + i) * 0.2;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: `${x}%`,
              top: `${y}%`,
              width: '64%',
              height: '64%',
              background: `radial-gradient(circle, ${color}66 0%, ${color}22 32%, transparent 70%)`,
              transform: `translate(-50%,-50%) scaleX(${sx}) scaleY(${sy})`,
              filter: `blur(${Math.round(Math.min(width, height) * 0.09)}px)`,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

/**
 * Concentric rings expanding from a point, on a stagger.
 *
 * Reads as broadcast, reach or propagation — which is what a ranking or
 * distribution story is usually about. Cheap, and it fills dead space in a
 * composition without adding another thing to read.
 */
export const PulseRings: React.FC<{
  palette: Palette;
  count?: number;
  speed?: number;
  x?: string;
  y?: string;
  maxFrac?: number;
}> = ({palette, count = 4, speed = 0.6, x = '50%', y = '50%', maxFrac = 1.1}) => {
  const {frame, fps, width} = useClip();
  const acc = accentOf(palette);
  const cycle = Math.max(1, fps / speed);
  const maxSize = width * maxFrac;

  return (
    <AbsoluteFill style={{overflow: 'hidden', pointerEvents: 'none'}}>
      {Array.from({length: count}).map((_, i) => {
        const p = ((frame + (i / count) * cycle) % cycle) / cycle;
        const size = interpolate(p, [0, 1], [0, maxSize]);
        const o = interpolate(p, [0, 0.2, 1], [0, 0.35, 0]);
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: x,
              top: y,
              width: size,
              height: size,
              marginLeft: -size / 2,
              marginTop: -size / 2,
              borderRadius: '50%',
              border: `2px solid ${acc}`,
              opacity: o,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

/**
 * Sub-pixel organic jitter, from @remotion/noise.
 *
 * A spring alone still lands on a perfectly straight path. A few pixels of
 * 2D-noise displacement, different per element, is what stops a row of animated
 * words looking like a spreadsheet animating. Deliberately tiny — at more than
 * ~4px it stops reading as life and starts reading as a wobble.
 */
export const jitter = (seed: string, frame: number, amount = 2.5) => ({
  x: noise2D(`${seed}-x`, frame * 0.01, 1) * amount,
  y: noise2D(`${seed}-y`, 1, frame * 0.01) * amount,
});
