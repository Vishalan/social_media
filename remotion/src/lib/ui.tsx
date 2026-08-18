import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT_CSS, SANS, MONO, bgOf, inkOf, accentOf, accent2Of, spacing, typeScale, Palette} from '../theme';
import {useClip, drift, at, blink} from './timing';
import {EXPO, pop, settle, ramp, wipe, focusIn, rand} from './motion';

/**
 * The layered backdrop every composition sits on.
 *
 * The first build painted one flat background colour with a single radial wash.
 * Flat colour is what made the graphics feel cheap next to the reference work:
 * there was no depth, so large type sat on nothing. Four cheap layers fix it —
 * a vertical base gradient, two slowly drifting colour orbs, a dot grid for
 * texture, and a vignette to hold the eye in the middle. None of it competes
 * with the content because none of it is above ~8% opacity.
 */
const Backdrop: React.FC<{palette: Palette}> = ({palette}) => {
  const {t, width, height} = useClip();
  const bg = bgOf(palette);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const dot = Math.max(18, Math.round(height * 0.028));

  return (
    <>
      <AbsoluteFill style={{background: `linear-gradient(160deg, ${bg} 0%, ${shade(bg, 14)} 55%, ${bg} 100%)`}} />
      {/* Drifting colour orbs: the whole reason the field reads as lit. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(closest-side, ${acc}2E, transparent)`,
          width: width * 1.1,
          height: width * 1.1,
          left: -width * 0.25 + t * width * 0.06,
          top: -height * 0.35 + t * height * 0.05,
          filter: 'blur(10px)',
        }}
      />
      <AbsoluteFill
        style={{
          background: `radial-gradient(closest-side, ${acc2}24, transparent)`,
          width: width * 0.95,
          height: width * 0.95,
          left: width * 0.45 - t * width * 0.05,
          top: height * 0.42 - t * height * 0.04,
          filter: 'blur(14px)',
        }}
      />
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(${inkOf(palette)}14 1.5px, transparent 1.6px)`,
          backgroundSize: `${dot}px ${dot}px`,
          opacity: 0.5,
        }}
      />
      <AbsoluteFill
        style={{background: `radial-gradient(120% 80% at 50% 45%, transparent 40%, ${bg}CC 100%)`}}
      />
    </>
  );
};

/** Lighten or darken a hex by a percentage, for gradient stops. */
const shade = (hex: string, pct: number): string => {
  const h = hex.replace('#', '');
  if (h.length !== 6) return hex;
  const v = [0, 2, 4].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16);
    return Math.max(0, Math.min(255, Math.round(c + (255 - c) * (pct / 100))));
  });
  return `#${v.map((c) => c.toString(16).padStart(2, '0')).join('')}`;
};

export const Frame: React.FC<{palette: Palette; children: React.ReactNode}> = ({
  palette,
  children,
}) => {
  const {t, height} = useClip();
  const s = spacing(height);
  return (
    <AbsoluteFill style={{background: bgOf(palette), fontFamily: SANS, color: inkOf(palette)}}>
      <style>{FONT_CSS}</style>
      <Backdrop palette={palette} />
      <AbsoluteFill
        style={{
          padding: s.pad,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'flex-start',
          transform: `scale(${drift(t)})`,
        }}
      >
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/**
 * A line of type that wipes into view word by word, with spring weight.
 *
 * Replaces an opacity fade with translate. A mask reveal plus a spring arrival
 * is the single biggest difference between "text appeared" and "text was
 * animated", and it is the technique under most of the kinetic typography in
 * Remotion's own showcase.
 */
export const Words: React.FC<{
  text: string;
  size: number;
  weight?: number;
  color?: string;
  accent?: string;
  accentFrom?: number;
  /** [start, end) word indices to accent — a phrase, not a tail. */
  accentRange?: [number, number];
  from?: number;
  to?: number;
  lineHeight?: number;
  gradient?: [string, string];
}> = ({text, size, weight = 900, color, accent, accentFrom, accentRange, from = 0.02, to = 0.66, lineHeight = 1.04, gradient}) => {
  const {t, frame, fps, durationInFrames} = useClip();
  const words = text.split(/\s+/).filter(Boolean);
  const slot = (to - from) / Math.max(1, words.length);

  return (
    <div style={{display: 'flex', flexWrap: 'wrap', width: '100%', gap: `0 ${size * 0.26}px`, lineHeight}}>
      {words.map((w, i) => {
        const start = from + slot * i;
        const p = ramp(t, start, Math.min(to, start + slot * 1.7));
        const sp = settle(frame, fps, Math.round(start * durationInFrames));
        // accentRange highlights a PHRASE; accentFrom colours a tail. Using
        // the tail form for a mid-sentence emphasis painted everything after
        // it, which defeats the point of having one focal target.
        const isAccent = accent !== undefined && (
          accentRange ? i >= accentRange[0] && i < accentRange[1]
                      : accentFrom !== undefined && i >= accentFrom);
        const grad = gradient && !isAccent;
        return (
          <span
            key={i}
            style={{
              fontSize: size,
              fontWeight: weight,
              letterSpacing: '-0.025em',
              // One colour decision, not three: a gradient word paints through
              // the text via background-clip and must therefore be transparent,
              // an accent word takes the accent, everything else takes the ink.
              color: grad ? 'transparent' : isAccent ? accent : color,
              backgroundImage: grad
                ? `linear-gradient(180deg, ${gradient![0]}, ${gradient![1]})`
                : undefined,
              WebkitBackgroundClip: grad ? 'text' : undefined,
              backgroundClip: grad ? ('text' as const) : undefined,
              display: 'inline-block',
              clipPath: wipe(p),
              transform: `translateY(${(1 - sp) * size * 0.16}px)`,
            }}
          >
            {w}
          </span>
        );
      })}
    </div>
  );
};

/** Uppercase eyebrow with a rule that draws itself. */
export const Kicker: React.FC<{
  text: string;
  palette: Palette;
  /** The source's own favicon as a data URI — its actual brand mark. */
  icon?: string;
}> = ({text, palette, icon}) => {
  const {t, frame, fps, height} = useClip();
  const ty = typeScale(height);
  const acc = accentOf(palette);
  const p = ramp(t, 0, 0.08);
  const sp = pop(frame, fps, 0);
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: height * 0.018,
        marginBottom: height * 0.032,
        transform: `translateX(${(1 - sp) * -18}px)`,
      }}
    >
      {icon ? (
        // The source's real mark, not an approximation of it. A colour alone
        // does not say "TechCrunch" to someone scrolling past; the favicon does.
        <img
          src={icon}
          style={{
            width: ty.label * 1.5,
            height: ty.label * 1.5,
            borderRadius: ty.label * 0.34,
            opacity: p,
            objectFit: 'contain',
          }}
        />
      ) : (
        <div
          style={{
            width: height * 0.014,
            height: ty.label * 1.05 * p,
            background: acc,
            borderRadius: 99,
            boxShadow: `0 0 ${height * 0.03}px ${acc}AA`,
          }}
        />
      )}
      <span
        style={{
          fontSize: ty.label,
          fontWeight: 800,
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
          color: acc,
          clipPath: wipe(p, 'left'),
        }}
      >
        {text}
      </span>
    </div>
  );
};

/** Elevated surface: layered shadow, hairline top highlight, faint tint. */
export const Card: React.FC<{
  palette: Palette;
  children: React.ReactNode;
  p?: number;
  style?: React.CSSProperties;
  tone?: 'neutral' | 'accent';
}> = ({palette, children, p = 1, style, tone = 'neutral'}) => {
  const {height} = useClip();
  const s = spacing(height);
  const acc = accentOf(palette);
  const ink = inkOf(palette);
  return (
    <div
      style={{
        position: 'relative',
        borderRadius: s.radius,
        padding: `${height * 0.028}px ${s.gap}px`,
        background: tone === 'accent' ? `${acc}1F` : `${ink}0D`,
        border: `2px solid ${tone === 'accent' ? `${acc}66` : `${ink}1F`}`,
        boxShadow: `0 ${height * 0.012}px ${height * 0.045}px rgba(0,0,0,0.45)`,
        backdropFilter: 'blur(2px)',
        opacity: p,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

/** Support copy under a hero. Capped so it never competes. */
export const Support: React.FC<{text: string; palette: Palette; from?: number}> = ({
  text,
  palette,
  from = 0.45,
}) => {
  const {t, height} = useClip();
  const ty = typeScale(height);
  const p = ramp(t, from, from + 0.22);
  return (
    <div
      style={{
        marginTop: height * 0.03,
        fontSize: ty.body,
        fontWeight: 600,
        lineHeight: 1.25,
        opacity: p * 0.9,
        clipPath: wipe(p),
        maxWidth: '94%',
      }}
    >
      {text}
    </div>
  );
};

/** Blinking block cursor — motion of last resort during settle. */
export const Cursor: React.FC<{size: number; color: string}> = ({size, color}) => {
  const {frame, fps} = useClip();
  return (
    <span
      style={{
        display: 'inline-block',
        width: size * 0.46,
        height: size * 0.92,
        background: color,
        opacity: blink(frame, fps),
        marginLeft: size * 0.14,
        verticalAlign: 'text-bottom',
        boxShadow: `0 0 ${size * 0.5}px ${color}88`,
      }}
    />
  );
};

export const monoFont = MONO;
export {shade};
