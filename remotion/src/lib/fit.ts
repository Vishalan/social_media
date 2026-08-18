import {fitText, measureText} from '@remotion/layout-utils';
import {SANS} from '../theme';

/**
 * Text fitting by MEASUREMENT, not by guessing character widths.
 *
 * Three rounds of this bug shipped before switching: sizes were derived from a
 * character-count times an assumed glyph-advance ratio, and the ratio was wrong
 * for Inter Black. "10-15x" clipped to "10-1"; then "shadowbanning" overflowed
 * the canvas by roughly 70px even after the ratio was corrected once, because a
 * single guessed constant cannot describe every string in every weight.
 *
 * @remotion/layout-utils measures against the real loaded font, so the answer is
 * exact and this whole class of clipping disappears rather than being retuned.
 */

const FAMILY = SANS;

/** Largest size at or below `max` where the whole string fits one line. */
export const fitOneLine = (
  text: string,
  max: number,
  availableWidth: number,
  fontWeight = 900,
  letterSpacing = '-0.03em',
): number => {
  if (!text) return max;
  const {fontSize} = fitText({
    text,
    withinWidth: availableWidth,
    fontFamily: FAMILY,
    fontWeight: String(fontWeight),
    letterSpacing,
  });
  return Math.min(max, fontSize);
};

/**
 * Largest size where every WORD fits the column, so wrapped text never clips.
 * Wrapping breaks at spaces, so the widest single word is the binding limit.
 */
export const fitWrapped = (
  text: string,
  max: number,
  availableWidth: number,
  fontWeight = 900,
  letterSpacing = '-0.02em',
): number => {
  const longest = text
    .split(/\s+/)
    .filter(Boolean)
    .reduce((a, b) => (b.length > a.length ? b : a), '');
  if (!longest) return max;
  return fitOneLine(longest, max, availableWidth, fontWeight, letterSpacing);
};

/** Width of a string at a given size — used to lay out inline runs. */
export const widthOf = (text: string, fontSize: number, fontWeight = 900) =>
  measureText({text, fontFamily: FAMILY, fontWeight: String(fontWeight), fontSize}).width;
