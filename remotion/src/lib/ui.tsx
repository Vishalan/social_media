import React from 'react';
import {AbsoluteFill} from 'remotion';
import {FONT_CSS, SANS, MONO, bgOf, inkOf, accentOf, spacing, typeScale, Palette} from '../theme';
import {useClip, drift, at, blink} from './timing';

/**
 * The frame every composition sits in.
 *
 * Owns the background, the padding, and the drift that keeps the clip alive.
 * Compositions therefore cannot forget any of the three.
 */
export const Frame: React.FC<{
  palette: Palette;
  children: React.ReactNode;
  align?: 'center' | 'start';
}> = ({palette, children, align = 'center'}) => {
  const {t, height} = useClip();
  const s = spacing(height);
  const bg = bgOf(palette);
  const acc = accentOf(palette);
  return (
    <AbsoluteFill style={{background: bg, fontFamily: SANS, color: inkOf(palette)}}>
      <style>{FONT_CSS}</style>
      {/* A soft accent wash, anchored off-centre so the field is never dead flat. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(120% 90% at 15% 0%, ${acc}22 0%, transparent 60%)`,
          transform: `scale(${drift(t, 0.04)})`,
        }}
      />
      <AbsoluteFill
        style={{
          padding: s.pad,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: align === 'center' ? 'center' : 'flex-start',
          alignItems: 'flex-start',
          transform: `scale(${drift(t)})`,
        }}
      >
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** A word-by-word build. Used wherever a line of copy must arrive with rhythm. */
export const Words: React.FC<{
  text: string;
  size: number;
  weight?: number;
  color?: string;
  accent?: string;
  accentFrom?: number;
  from?: number;
  to?: number;
  lineHeight?: number;
}> = ({text, size, weight = 900, color, accent, accentFrom, from, to, lineHeight = 1.06}) => {
  const {t} = useClip();
  const words = text.split(/\s+/).filter(Boolean);
  return (
    // width:100% is load-bearing. Without it this flex row is width:auto in a
    // column parent, which resolves to max-content — so flex-wrap never fires
    // and a long headline runs straight off the canvas instead of wrapping.
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        width: '100%',
        gap: `0 ${size * 0.26}px`,
        lineHeight,
      }}
    >
      {words.map((w, i) => {
        const p = staggerWords(t, i, words.length, from, to);
        const isAccent = accent !== undefined && accentFrom !== undefined && i >= accentFrom;
        return (
          <span
            key={i}
            style={{
              fontSize: size,
              fontWeight: weight,
              letterSpacing: '-0.02em',
              color: isAccent ? accent : color,
              opacity: p,
              transform: `translateY(${(1 - p) * size * 0.22}px)`,
              display: 'inline-block',
            }}
          >
            {w}
          </span>
        );
      })}
    </div>
  );
};

const staggerWords = (t: number, i: number, n: number, from = 0.1, to = 0.7) => {
  const slot = (to - from) / Math.max(1, n);
  return at(t, from + slot * i, from + slot * (i + 1.6));
};

/** A small uppercase eyebrow. Gives every card an anchor at the top-left. */
export const Kicker: React.FC<{text: string; palette: Palette}> = ({text, palette}) => {
  const {t, height} = useClip();
  const ty = typeScale(height);
  const acc = accentOf(palette);
  const p = at(t, 0, 0.1);
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: height * 0.018,
        opacity: p,
        transform: `translateX(${(1 - p) * -20}px)`,
        marginBottom: height * 0.03,
      }}
    >
      <div style={{width: height * 0.012, height: ty.label * 0.9, background: acc, borderRadius: 99}} />
      <span
        style={{
          fontSize: ty.label,
          fontWeight: 700,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: acc,
        }}
      >
        {text}
      </span>
    </div>
  );
};

/** Support copy under a hero. Never competes: capped below the hero's size. */
export const Support: React.FC<{text: string; palette: Palette; from?: number}> = ({
  text,
  palette,
  from = 0.45,
}) => {
  const {t, height} = useClip();
  const ty = typeScale(height);
  const p = at(t, from, from + 0.22);
  return (
    <div
      style={{
        marginTop: height * 0.03,
        fontSize: ty.body,
        fontWeight: 600,
        lineHeight: 1.25,
        opacity: p * 0.92,
        transform: `translateY(${(1 - p) * 18}px)`,
        maxWidth: '94%',
      }}
    >
      {text}
    </div>
  );
};

/** A blinking block cursor — the motion of last resort during settle. */
export const Cursor: React.FC<{size: number; color: string}> = ({size, color}) => {
  const {frame, fps} = useClip();
  return (
    <span
      style={{
        display: 'inline-block',
        width: size * 0.5,
        height: size * 0.95,
        background: color,
        opacity: blink(frame, fps),
        marginLeft: size * 0.12,
        verticalAlign: 'text-bottom',
      }}
    />
  );
};

export const monoFont = MONO;
