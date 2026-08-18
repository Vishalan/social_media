import React from 'react';
import {Frame, Kicker, Words, Cursor} from '../lib/ui';
import {useClip, at} from '../lib/timing';
import {typeScale, accentOf, inkOf, spacing, Palette} from '../theme';
import {fitWrapped} from '../lib/fit';

export type HeadlineBurstProps = {
  palette: Palette;
  headline: string;
  support?: string;
  kicker?: string;
  /** Word index from which the headline switches to the accent colour. */
  accentFrom?: number;
};

/**
 * A claim, built word by word, filling the frame.
 *
 * Size is chosen from the word count rather than fixed, so a three-word hook
 * lands enormous and a twelve-word claim still fits without wrapping into a
 * cramped block. The old version used one size for everything and left half the
 * panel empty on short copy.
 */
export const HeadlineBurst: React.FC<HeadlineBurstProps> = ({
  palette,
  headline,
  support,
  kicker,
  accentFrom,
}) => {
  const {t, height, width} = useClip();
  const ty = typeScale(height);
  const acc = accentOf(palette);
  const n = headline.split(/\s+/).filter(Boolean).length;
  const byCount = n <= 3 ? ty.solo * 0.72 : n <= 6 ? ty.hero * 1.35 : n <= 10 ? ty.hero : ty.title;
  // The widest WORD is the real constraint: 'shadowbanning' at the size the
  // word count suggested was ~1420px on a 1080px canvas and clipped.
  const size = fitWrapped(headline, byCount, width - spacing(height).pad * 2);

  return (
    <Frame palette={palette}>
      {kicker ? <Kicker text={kicker} palette={palette} /> : null}
      <Words
        text={headline}
        size={size}
        color={inkOf(palette)}
        accent={acc}
        accentFrom={accentFrom}
        from={0.08}
        to={0.66}
      />
      {/* width:100% so the rule's percentage resolves against the canvas. In an
          auto-width flex row it resolved against the row's own shrink-to-fit
          width and collapsed the rule to a dot. */}
      <div style={{display: 'flex', width: '100%', alignItems: 'flex-end', marginTop: height * 0.01}}>
        <div
          style={{
            height: height * 0.012,
            width: `${20 + 40 * at(t, 0.3, 0.98)}%`,
            background: acc,
            borderRadius: 99,
          }}
        />
        <Cursor size={size * 0.5} color={acc} />
      </div>
      {support ? <Support2 text={support} palette={palette} /> : null}
    </Frame>
  );
};

const Support2: React.FC<{text: string; palette: Palette}> = ({text, palette}) => {
  const {t, height, width} = useClip();
  const ty = typeScale(height);
  const p = at(t, 0.6, 0.85);
  return (
    <div
      style={{
        marginTop: height * 0.035,
        fontSize: ty.body,
        fontWeight: 600,
        opacity: p * 0.88,
        transform: `translateY(${(1 - p) * 16}px)`,
        maxWidth: '92%',
        lineHeight: 1.25,
      }}
    >
      {text}
    </div>
  );
};
