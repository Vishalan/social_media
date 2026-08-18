import React from 'react';
import {Frame, Kicker, Words} from '../lib/ui';
import {useClip} from '../lib/timing';
import {ramp} from '../lib/motion';
import {typeScale, spacing, accentOf, accent2Of, inkOf, Palette} from '../theme';
import {fitWrapped} from '../lib/fit';

export type SourcePullProps = {
  palette: Palette;
  /** ONE sentence from the source. Never a paragraph. */
  sentence: string;
  /** Where it came from, e.g. "techcrunch.com". */
  attribution?: string;
  /** An exact phrase inside the sentence to accent. */
  emphasis?: string;
};

/**
 * One sentence from the source, at a size you can actually read.
 *
 * This replaces the reader-page bed, which rendered four paragraphs of
 * equal-weight body copy clipped top and bottom. That had no focal point at
 * all — every line competed with every other, so there was nowhere for the eye
 * to land, and the paragraph the panel was supposedly framing was cut through
 * the middle of its first line.
 *
 * A bed still has to stay quieter than a designed graphic, or it competes with
 * the beat it is filling between. It earns that by being ONE sentence at large
 * type with a single accented phrase, rather than by being small.
 */
export const SourcePull: React.FC<SourcePullProps> = ({
  palette,
  sentence,
  attribution,
  emphasis,
}) => {
  const {t, height, width} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const ink = inkOf(palette);

  const words = sentence.split(/\s+/).filter(Boolean);
  const byCount = words.length <= 10 ? ty.hero : words.length <= 18 ? ty.title : ty.body * 1.35;
  const size = fitWrapped(sentence, byCount, width - s.pad * 2, 700);

  // Accent the emphasis phrase where it appears, so the eye has ONE target.
  const emphasisWords = (emphasis || '').split(/\s+/).filter(Boolean);
  let accentRange: [number, number] | undefined;
  if (emphasisWords.length) {
    const norm = (x: string) => x.toLowerCase().replace(/[^a-z0-9]/g, '');
    const first = norm(emphasisWords[0]);
    const idx = words.findIndex((w) => norm(w) === first);
    if (idx >= 0) accentRange = [idx, idx + emphasisWords.length];
  }

  return (
    <Frame palette={palette}>
      {attribution ? <Kicker text={attribution} palette={palette} /> : null}
      <div
        style={{
          borderLeft: `${height * 0.008}px solid ${acc}`,
          paddingLeft: s.gap * 0.7,
        }}
      >
        <Words
          text={sentence}
          size={size}
          weight={700}
          color={ink}
          accent={acc}
          accentRange={accentRange}
          from={0.02}
          to={0.4}
          lineHeight={1.22}
        />
      </div>
      <div
        style={{
          height: height * 0.01,
          width: `${16 + 30 * ramp(t, 0.2, 0.7)}%`,
          background: `linear-gradient(90deg, ${acc}, ${acc2})`,
          borderRadius: 99,
          marginTop: height * 0.03,
          opacity: 0.8,
        }}
      />
    </Frame>
  );
};
