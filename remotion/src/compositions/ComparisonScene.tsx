import React from 'react';
import {AbsoluteFill, interpolate, Easing} from 'remotion';
import {useClip} from '../lib/timing';
import {World, slowPush, At} from '../lib/stage';
import {ramp} from '../lib/motion';
import {typeScale, spacing, accentOf, accent2Of, inkOf, bgOf, Palette,
        SANS, MONO, FONT_CSS, contrastRatio, onColor} from '../theme';
import {fitOneLine} from '../lib/fit';

export type Contender = {
  label: string;
  /** The number itself, e.g. 10 — counted up to, not printed. */
  value: number;
  /** Rendered around the value, e.g. "$" and "B". */
  prefix?: string;
  suffix?: string;
  /** Marks the winner/subject of the story. */
  lead?: boolean;
};

export type ComparisonSceneProps = {
  palette: Palette;
  kicker?: string;
  title?: string;
  items: Contender[];
  /** One line under the bars: what the comparison MEANS. */
  note?: string;
};

/**
 * Two or three quantities, compared as bars that grow and numbers that count.
 *
 * The gap this fills: every scene built so far assumes software to point a
 * camera at — a terminal, a phone, a window, a pipeline. Stories about money,
 * companies and policy have none of those, so they fell back to typographic
 * cards, and a video about an IPO came out as five rectangles of text.
 *
 * A comparison is the shape most business stories actually have — bigger than,
 * ahead of, more than — and it is genuinely visual: the bar carries the
 * meaning, and a viewer who reads nothing still sees which one is longer. The
 * number counts up rather than appearing, because a figure that ticks is
 * watched and a figure that is simply printed is read once and dismissed.
 */
export const ComparisonScene: React.FC<ComparisonSceneProps> = ({
  palette, kicker, title, items, note,
}) => {
  const {t, frame, height, width, durationInFrames} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const ink = inkOf(palette);
  const bg = bgOf(palette);

  const rows = items.slice(0, 3);
  const max = Math.max(...rows.map((r) => r.value), 1);

  const cx = width / 2;
  const cy = height / 2;
  const stops = slowPush(durationInFrames, cx, cy, 1.10);

  const barW = width - s.pad * 2;
  // Sized to FILL the frame it was given. The first version used fractions
  // tuned against a half-height panel, so at full frame the whole comparison
  // sat in the middle 40% with dead space above and below — the bars were
  // the content and they were the smallest thing on screen.
  const barH = Math.min(height * 0.115, barW * 0.20);
  const gap = barH * 1.45;

  return (
    <AbsoluteFill style={{background: bg, fontFamily: SANS, color: ink}}>
      <style>{FONT_CSS}</style>
      <AbsoluteFill
        style={{
          background:
            `radial-gradient(80% 50% at 50% 8%, ${acc}1A, transparent 60%)`,
        }}
      />
      <World frame={frame} stops={stops} width={width} height={height} trail={false}>
        <At x={cx} y={cy}>
          <div style={{width: barW, display: 'flex', flexDirection: 'column',
                       alignItems: 'flex-start'}}>
            {kicker ? (
              <div style={{
                fontSize: fitOneLine(kicker.toUpperCase(), ty.label, barW, 800, '0.16em'),
                fontWeight: 800, letterSpacing: '0.16em', whiteSpace: 'nowrap',
                textTransform: 'uppercase', color: acc,
                marginBottom: barH * 0.30, opacity: ramp(t, 0, 0.08),
              }}>{kicker}</div>
            ) : null}
            {title ? (
              <div style={{
                fontSize: fitOneLine(title, ty.hero * 0.78, barW, 900, '-0.02em'),
                fontWeight: 900, letterSpacing: '-0.02em', whiteSpace: 'nowrap',
                marginBottom: barH * 0.62, opacity: ramp(t, 0.02, 0.12),
              }}>{title}</div>
            ) : null}

            {rows.map((r, i) => {
              // Each bar starts after the one above it has largely arrived, so
              // the eye follows a sequence rather than seeing them all move.
              const from = 0.12 + i * 0.16;
              const grow = interpolate(t, [from, from + 0.42], [0, 1], {
                easing: Easing.out(Easing.cubic),
                extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
              });
              const frac = (r.value / max) * grow;
              const shown = r.value * grow;
              // Whole numbers below 100 read better than 2 decimals at speed.
              const text = `${r.prefix ?? ''}${
                r.value >= 100 ? Math.round(shown).toLocaleString()
                               : shown.toFixed(shown < 10 ? 1 : 0)
              }${r.suffix ?? ''}`;
              const fill = r.lead ? acc : acc2;
              const labelSize = Math.min(ty.body * 1.0, barH * 0.40);
              const valueSize = Math.min(ty.hero * 0.62, barH * 0.56);
              return (
                <div key={i} style={{width: '100%', marginBottom: gap - barH}}>
                  <div style={{
                    display: 'flex', justifyContent: 'space-between',
                    alignItems: 'baseline', marginBottom: barH * 0.16,
                    opacity: ramp(t, from - 0.04, from + 0.06),
                  }}>
                    <div style={{
                      fontSize: fitOneLine(r.label, labelSize, barW * 0.62, 800, '0em'),
                      fontWeight: 800, whiteSpace: 'nowrap',
                      color: r.lead ? ink : `${ink}B0`,
                    }}>{r.label}</div>
                    <div style={{
                      fontFamily: MONO, fontSize: valueSize, fontWeight: 800,
                      color: r.lead ? acc : `${ink}C0`,
                    }}>{text}</div>
                  </div>
                  {/* The bar itself. A track behind it so a short bar still
                      reads as a measurement rather than a stray rectangle. */}
                  <div style={{
                    width: '100%', height: barH, borderRadius: barH * 0.22,
                    background: `${ink}1F`, overflow: 'hidden',
                  }}>
                    <div style={{
                      width: `${Math.max(0, Math.min(1, frac)) * 100}%`,
                      height: '100%', borderRadius: barH * 0.22,
                      // The non-leading bar carries half the meaning — it is
                      // the thing being beaten — so it cannot be a whisper.
                      // At 22% ink over a mid-tone track it was invisible,
                      // which left the comparison with nothing to compare.
                      background: r.lead
                        ? `linear-gradient(90deg, ${acc}, ${acc2})`
                        : `${ink}80`,
                      boxShadow: r.lead ? `0 0 ${barH * 0.5}px ${acc}44` : undefined,
                    }} />
                  </div>
                </div>
              );
            })}

            {note ? (
              <div style={{
                marginTop: barH * 0.5,
                fontSize: fitOneLine(note, ty.body * 0.78, barW, 700, '0em'),
                fontWeight: 700, whiteSpace: 'nowrap',
                color: contrastRatio(acc, bg) >= 4.5 ? acc : ink,
                opacity: ramp(t, 0.62, 0.76),
              }}>{note}</div>
            ) : null}
          </div>
        </At>
      </World>
    </AbsoluteFill>
  );
};
