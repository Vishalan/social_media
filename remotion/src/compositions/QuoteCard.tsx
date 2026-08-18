import React from 'react';
import {Frame} from '../lib/ui';
import {useClip, at} from '../lib/timing';
import {typeScale, spacing, accentOf, inkOf, Palette} from '../theme';
import {fitWrapped} from '../lib/fit';

export type QuoteCardProps = {
  palette: Palette;
  quote: string;
  author: string;
  role?: string;
};

/** A named human saying something. Never used for company statements. */
export const QuoteCard: React.FC<QuoteCardProps> = ({palette, quote, author, role}) => {
  const {t, height, width} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const ink = inkOf(palette);

  const words = quote.split(/\s+/).filter(Boolean);
  const byCount = words.length <= 12 ? ty.title : ty.body * 1.25;
  const size = fitWrapped(quote, byCount, width - spacing(height).pad * 2, 700, '0em');
  const pMark = at(t, 0, 0.1);
  const pAuthor = at(t, 0.66, 0.88);

  return (
    <Frame palette={palette} >
      <div
        style={{
          fontSize: ty.solo * 0.7,
          lineHeight: 0.7,
          color: acc,
          fontWeight: 900,
          opacity: pMark,
          transform: `translateY(${(1 - pMark) * -18}px)`,
        }}
      >
        &ldquo;
      </div>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          width: '100%',
          gap: `0 ${size * 0.28}px`,
          marginTop: s.gap * 0.4,
        }}
      >
        {words.map((w, i) => {
          const slot = (0.62 - 0.03) / words.length;
          const p = at(t, 0.03 + slot * i, 0.03 + slot * (i + 1.7));
          return (
            <span
              key={i}
              style={{
                fontSize: size,
                fontWeight: 700,
                lineHeight: 1.22,
                color: ink,
                opacity: p,
                transform: `translateY(${(1 - p) * 14}px)`,
                display: 'inline-block',
              }}
            >
              {w}
            </span>
          );
        })}
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: s.gap * 0.6,
          marginTop: s.gap,
          opacity: pAuthor,
          transform: `translateX(${(1 - pAuthor) * -22}px)`,
        }}
      >
        <div style={{width: height * 0.01, height: ty.body * 1.6, background: acc, borderRadius: 99}} />
        <div>
          <div style={{fontSize: ty.body, fontWeight: 900, color: ink}}>{author}</div>
          {role ? (
            <div style={{fontSize: ty.label, fontWeight: 600, color: `${ink}99`, marginTop: height * 0.006}}>
              {role}
            </div>
          ) : null}
        </div>
      </div>
    </Frame>
  );
};
