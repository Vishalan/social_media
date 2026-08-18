import React from 'react';
import {Frame, Kicker, Words, Cursor} from '../lib/ui';
import {useClip} from '../lib/timing';
import {ramp} from '../lib/motion';
import {typeScale, spacing, accentOf, accent2Of, inkOf, Palette} from '../theme';
import {fitWrapped, fitBlock} from '../lib/fit';

export type HeadlineBurstProps = {
  palette: Palette;
  headline: string;
  support?: string;
  kicker?: string;
  accentFrom?: number;
};

/**
 * A claim, wiped in word by word, with the payoff half in the accent.
 *
 * Size comes from the word count and is then bound by MEASURING the widest
 * word, so a three-word hook lands enormous and a twelve-word claim still wraps
 * without clipping.
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
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const ink = inkOf(palette);
  const n = headline.split(/\s+/).filter(Boolean).length;
  const byCount = n <= 3 ? ty.solo * 0.7 : n <= 6 ? ty.hero * 1.3 : n <= 10 ? ty.hero : ty.title;
  // Both axes. Width alone let an eight-word headline wrap to six lines and
  // run off the panel; the kicker and the rule below also take height.
  const reserved = (kicker ? ty.label * 2.9 : 0) + height * 0.10;
  const size = Math.min(
    fitWrapped(headline, byCount, width - s.pad * 2),
    fitBlock(headline, byCount, width - s.pad * 2,
             height - s.pad * 2 - reserved, {lineHeight: 1.06}),
  );

  return (
    <Frame palette={palette}>
      {kicker ? <Kicker text={kicker} palette={palette} /> : null}
      <Words
        text={headline}
        size={size}
        color={ink}
        accent={acc}
        accentFrom={accentFrom}
        from={0.02}
        to={0.42}
      />
      <div style={{display: 'flex', width: '100%', alignItems: 'flex-end', marginTop: height * 0.022}}>
        <div
          style={{
            height: height * 0.014,
            width: `${18 + 44 * ramp(t, 0.2, 0.6)}%`,
            background: `linear-gradient(90deg, ${acc}, ${acc2})`,
            borderRadius: 99,
            boxShadow: `0 0 ${height * 0.045}px ${acc}66`,
          }}
        />
        <Cursor size={size * 0.42} color={acc} />
      </div>
      {support ? (
        <div
          style={{
            marginTop: height * 0.03,
            fontSize: ty.body,
            fontWeight: 600,
            opacity: 0.88 * ramp(t, 0.4, 0.56),
            maxWidth: '92%',
            lineHeight: 1.25,
          }}
        >
          {support}
        </div>
      ) : null}
    </Frame>
  );
};
