import React from 'react';
import {Frame, Kicker, Support} from '../lib/ui';
import {useClip, at} from '../lib/timing';
import {ramp, settle, wipe} from '../lib/motion';
import {typeScale, spacing, accentOf, accent2Of, inkOf, Palette} from '../theme';
import {fitOneLine} from '../lib/fit';

export type StatCardProps = {
  /** The SUBJECT's mark — see broll_director.render_designed. */
  icon?: string;
  palette: Palette;
  value: string;
  support?: string;
  kicker?: string;
};

/**
 * One hard figure, at the largest type in the system, on a lit field.
 *
 * The figure is painted with a vertical gradient and sits over a large ghosted
 * copy of itself — the trick most "big number" motion graphics use to stop a
 * numeral looking like plain text on a plain background. Digits roll up into
 * place rather than fading, so the count reads as a mechanism rather than a
 * crossfade.
 */
export const StatCard: React.FC<StatCardProps> = ({palette, icon, value, support, kicker}) => {
  const {t, frame, fps, height, width} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const ink = inkOf(palette);

  const heroSize = fitOneLine(value, ty.solo, width - s.pad * 2, 900, '-0.045em');
  const p = ramp(t, 0.04, 0.42);
  const sp = settle(frame, fps, 0);

  // Roll only the numeric runs, so "10-15x" keeps its separator and unit while
  // its digits count. Animating the whole string produced nonsense frames.
  const rolled = value.replace(/[\d.,]+/g, (n) => {
    const num = parseFloat(n.replace(/,/g, ''));
    if (!isFinite(num)) return n;
    const dp = (n.split('.')[1] || '').length;
    return (num * p).toFixed(dp);
  });

  return (
    <Frame palette={palette}>
      {kicker ? <Kicker text={kicker} palette={palette} icon={icon} /> : null}
      <div style={{position: 'relative', width: '100%'}}>
        {/* Ghost copy: gives the numeral depth instead of floating on flat colour. */}
        <div
          aria-hidden
          style={{
            position: 'absolute',
            inset: 0,
            fontSize: heroSize,
            fontWeight: 900,
            lineHeight: 0.92,
            letterSpacing: '-0.045em',
            color: acc,
            opacity: 0.16,
            filter: `blur(${height * 0.02}px)`,
            transform: `translate(${height * 0.012}px, ${height * 0.014}px) scale(${0.98 + 0.02 * sp})`,
          }}
        >
          {rolled}
        </div>
        <div
          style={{
            position: 'relative',
            fontSize: heroSize,
            fontWeight: 900,
            lineHeight: 0.92,
            letterSpacing: '-0.045em',
            fontVariantNumeric: 'tabular-nums',
            backgroundImage: `linear-gradient(170deg, ${ink} 30%, ${acc} 130%)`,
            WebkitBackgroundClip: 'text',
            backgroundClip: 'text',
            color: 'transparent',
            clipPath: wipe(ramp(t, 0.02, 0.36)),
            transform: `translateY(${(1 - sp) * heroSize * 0.1}px)`,
          }}
        >
          {rolled}
        </div>
      </div>
      <div
        style={{
          height: height * 0.016,
          width: `${26 + 64 * ramp(t, 0.12, 0.55)}%`,
          background: `linear-gradient(90deg, ${acc}, ${acc2})`,
          borderRadius: 99,
          marginTop: height * 0.03,
          boxShadow: `0 0 ${height * 0.05}px ${acc}66`,
        }}
      />
      {support ? <Support text={support} palette={palette} from={0.3} /> : null}
    </Frame>
  );
};
