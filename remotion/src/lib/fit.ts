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

/**
 * Fit a wrapping block of text to BOTH axes.
 *
 * fitWrapped only ever constrained width — it guarantees no single word is
 * wider than the column, and says nothing about how many lines the result
 * takes. An eight-word headline at hero size wrapped to six lines and ran off
 * the panel top and bottom: "Every" clipped above, "source" clipped below.
 * Width was measured; height was assumed.
 *
 * This wraps the words exactly the way the flex row does — measuring each word
 * and adding the same inter-word gap the component applies — then shrinks until
 * the resulting block fits the height it has been given.
 */
export const fitBlock = (
  text: string,
  maxSize: number,
  availableWidth: number,
  availableHeight: number,
  {
    lineHeight = 1.06,
    fontWeight = 900,
    letterSpacing = '-0.025em',
    gapRatio = 0.26,
  }: {
    lineHeight?: number;
    fontWeight?: number;
    letterSpacing?: string;
    gapRatio?: number;
  } = {},
): number => {
  const words = text.split(/\s+/).filter(Boolean);
  if (!words.length) return maxSize;

  const linesAt = (size: number): number => {
    const gap = size * gapRatio;
    let lines = 1;
    let used = 0;
    for (const w of words) {
      const {width} = measureText({
        text: w,
        fontFamily: FAMILY,
        fontWeight: String(fontWeight),
        fontSize: size,
        letterSpacing,
      });
      // A word wider than the column gets its own line and overflows; the
      // width fit is what prevents that, so it is not re-solved here.
      const advance = used === 0 ? width : gap + width;
      if (used + advance > availableWidth && used > 0) {
        lines += 1;
        used = width;
      } else {
        used += advance;
      }
    }
    return lines;
  };

  let size = maxSize;
  // Geometric shrink: 24 steps at 0.94 covers a 4x reduction, far more than any
  // real case needs, and terminates regardless of the text.
  for (let i = 0; i < 24; i++) {
    if (linesAt(size) * size * lineHeight <= availableHeight) return size;
    size *= 0.94;
    if (size < 14) break;
  }
  return size;
};
