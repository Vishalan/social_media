import React from 'react';
import {Frame, Kicker, Cursor} from '../lib/ui';
import {useClip} from '../lib/timing';
import {ramp, settle, pop, wipe} from '../lib/motion';
import {typeScale, spacing, accentOf, accent2Of, inkOf, Palette, MONO} from '../theme';
import {fitWrapped} from '../lib/fit';

export type LockupProps = {
  palette: Palette;
  kicker?: string;
  title: string;
  badge?: string;
  typed?: string;
};

/**
 * A name, a badge, and a line that types itself in.
 *
 * The typewriter is the settle-phase motion: it is still revealing characters
 * while the reader takes in the title, so the clip stays alive for its whole
 * length without a second idea competing with the first. The title carries the
 * gradient and a soft glow so a single word still fills the frame with weight.
 */
export const Lockup: React.FC<LockupProps> = ({palette, kicker, title, badge, typed}) => {
  const {t, frame, fps, height, width} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const ink = inkOf(palette);

  const titleSize = fitWrapped(title, ty.solo * 0.62, width - s.pad * 2, 900, '-0.04em');
  const pTitle = ramp(t, 0.02, 0.28);
  const spTitle = settle(frame, fps, 0);
  const pBadge = ramp(t, 0.22, 0.38);
  const spBadge = pop(frame, fps, Math.round(0.3 * fps * 2));
  // Deliberately still typing at 92% of the clip.
  const chars = typed ? Math.floor(typed.length * ramp(t, 0.3, 0.8)) : 0;

  return (
    <Frame palette={palette}>
      {kicker ? <Kicker text={kicker} palette={palette} /> : null}
      <div
        style={{
          fontSize: titleSize,
          fontWeight: 900,
          letterSpacing: '-0.04em',
          lineHeight: 0.96,
          backgroundImage: `linear-gradient(165deg, ${ink} 35%, ${acc} 125%)`,
          WebkitBackgroundClip: 'text',
          backgroundClip: 'text',
          color: 'transparent',
          clipPath: wipe(pTitle),
          transform: `translateY(${(1 - spTitle) * titleSize * 0.12}px)`,
          filter: `drop-shadow(0 ${height * 0.012}px ${height * 0.04}px ${acc}44)`,
        }}
      >
        {title}
      </div>
      {badge ? (
        <div
          style={{
            marginTop: s.gap * 0.7,
            padding: `${height * 0.017}px ${height * 0.036}px`,
            borderRadius: 999,
            border: `2px solid ${acc}`,
            background: `${acc}1A`,
            color: acc,
            fontSize: ty.label * 1.12,
            fontWeight: 800,
            letterSpacing: '0.02em',
            opacity: pBadge,
            transform: `scale(${0.86 + 0.14 * spBadge})`,
            transformOrigin: 'left center',
            boxShadow: `0 0 ${height * 0.04}px ${acc}44`,
          }}
        >
          {badge}
        </div>
      ) : null}
      {typed ? (
        <div
          style={{
            marginTop: s.gap * 0.95,
            fontFamily: MONO,
            fontSize: Math.max(ty.floor, ty.mono * 0.95),
            lineHeight: 1.45,
            color: `${ink}DD`,
            maxWidth: '96%',
            borderLeft: `3px solid ${acc2}`,
            paddingLeft: s.gap * 0.5,
          }}
        >
          {typed.slice(0, chars)}
          <Cursor size={ty.mono} color={acc} />
        </div>
      ) : null}
    </Frame>
  );
};
