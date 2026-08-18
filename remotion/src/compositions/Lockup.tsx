import React from 'react';
import {Frame, Kicker, Cursor} from '../lib/ui';
import {useClip, at} from '../lib/timing';
import {typeScale, spacing, accentOf, inkOf, Palette, MONO} from '../theme';
import {fitWrapped} from '../lib/fit';

export type LockupProps = {
  palette: Palette;
  kicker?: string;
  /** The name being locked up: "Apache v2", "Grok", "Phoenix". */
  title: string;
  /** A pill under the title, e.g. "open source license". */
  badge?: string;
  /** A monospace line that types itself in during the build. */
  typed?: string;
};

/**
 * A name, a badge, and a line that types itself in.
 *
 * The typewriter is the settle-phase motion: it is still revealing characters
 * while the reader is taking in the title, so the clip has something happening
 * for its whole length without a second idea competing with the first.
 */
export const Lockup: React.FC<LockupProps> = ({palette, kicker, title, badge, typed}) => {
  const {t, height, width} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const ink = inkOf(palette);

  // Same two-axis fit as StatCard: a long name must not run off the canvas.
  const titleSize = fitWrapped(title, ty.solo * 0.62, width - s.pad * 2, 900, '-0.04em');
  const pTitle = at(t, 0.05, 0.4);
  const pBadge = at(t, 0.34, 0.56);
  // Deliberately still typing at 92% of the clip.
  const chars = typed ? Math.floor(typed.length * at(t, 0.42, 0.92)) : 0;

  return (
    <Frame palette={palette} >
      {kicker ? <Kicker text={kicker} palette={palette} /> : null}
      <div
        style={{
          fontSize: titleSize,
          fontWeight: 900,
          letterSpacing: '-0.04em',
          lineHeight: 0.95,
          color: ink,
          opacity: pTitle,
          transform: `translateY(${(1 - pTitle) * 26}px)`,
        }}
      >
        {title}
      </div>
      {badge ? (
        <div
          style={{
            marginTop: s.gap * 0.7,
            padding: `${height * 0.016}px ${height * 0.034}px`,
            borderRadius: 999,
            border: `2px solid ${acc}`,
            color: acc,
            fontSize: ty.label * 1.1,
            fontWeight: 800,
            opacity: pBadge,
            transform: `scale(${0.88 + 0.12 * pBadge})`,
            transformOrigin: 'left center',
          }}
        >
          {badge}
        </div>
      ) : null}
      {typed ? (
        <div
          style={{
            marginTop: s.gap,
            fontFamily: MONO,
            fontSize: Math.max(ty.floor, ty.mono * 0.95),
            lineHeight: 1.4,
            color: `${ink}DD`,
            maxWidth: '96%',
          }}
        >
          {typed.slice(0, chars)}
          <Cursor size={ty.mono} color={acc} />
        </div>
      ) : null}
    </Frame>
  );
};
