import React from 'react';
import {Frame, Kicker} from '../lib/ui';
import {useClip} from '../lib/timing';
import {ramp, pop, settle, wipe} from '../lib/motion';
import {typeScale, spacing, accentOf, accent2Of, inkOf, Palette} from '../theme';
import {fitOneLine, fitWrapped} from '../lib/fit';

export type CtaCardProps = {
  palette: Palette;
  /** The instruction, e.g. "Comment ALGORITHM and I'll send the repo link". */
  action: string;
  /** The single word to type, if the CTA is a keyword one. */
  keyword?: string;
  kicker?: string;
};

/**
 * The call to action, as a card the viewer can actually act on.
 *
 * A keyword CTA that is only spoken is a CTA nobody completes: the viewer hears
 * "comment ALGORITHM", has no idea how it is spelled, and scrolls. The word has
 * to be ON SCREEN, at the largest size in the card, held long enough to type.
 *
 * The keyword therefore gets hero treatment and the instruction is demoted to
 * support — the reverse of every other composition here, where the sentence
 * leads. It also pulses, gently and continuously: this is the one card where a
 * little attention-seeking is the entire point.
 */
export const CtaCard: React.FC<CtaCardProps> = ({palette, action, keyword, kicker}) => {
  const {t, frame, fps, height, width} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const ink = inkOf(palette);

  const pKick = ramp(t, 0, 0.1);
  const spWord = pop(frame, fps, 0);
  const pAction = ramp(t, 0.25, 0.5);
  // A slow breath, running the whole clip so the card never sits still.
  const pulse = 1 + 0.02 * Math.sin((frame / Math.max(1, fps)) * 2.2);

  const wordSize = keyword
    ? fitOneLine(keyword, ty.solo * 0.78, width - s.pad * 2.4, 900, '-0.02em')
    : 0;
  const actionSize = fitWrapped(action, ty.body * 1.15, width - s.pad * 2, 700);

  return (
    <Frame palette={palette}>
      {kicker ? <Kicker text={kicker} palette={palette} /> : null}

      {keyword ? (
        <div
          style={{
            alignSelf: 'stretch',
            display: 'flex',
            justifyContent: 'center',
            padding: `${height * 0.03}px ${s.gap}px`,
            borderRadius: s.radius,
            background: `${acc}1A`,
            border: `3px solid ${acc}`,
            boxShadow: `0 0 ${height * 0.06}px ${acc}55`,
            transform: `scale(${(0.9 + 0.1 * spWord) * pulse})`,
            marginBottom: height * 0.035,
          }}
        >
          <span
            style={{
              fontSize: wordSize,
              fontWeight: 900,
              letterSpacing: '0.01em',
              lineHeight: 1,
              backgroundImage: `linear-gradient(150deg, ${ink} 25%, ${acc} 120%)`,
              WebkitBackgroundClip: 'text',
              backgroundClip: 'text',
              color: 'transparent',
            }}
          >
            {keyword}
          </span>
        </div>
      ) : null}

      <div
        style={{
          fontSize: actionSize,
          fontWeight: 700,
          lineHeight: 1.25,
          color: ink,
          clipPath: wipe(pAction),
          maxWidth: '96%',
        }}
      >
        {action}
      </div>

      <div
        style={{
          height: height * 0.012,
          width: `${24 + 52 * ramp(t, 0.3, 0.95)}%`,
          background: `linear-gradient(90deg, ${acc}, ${acc2})`,
          borderRadius: 99,
          marginTop: height * 0.03,
        }}
      />
    </Frame>
  );
};
