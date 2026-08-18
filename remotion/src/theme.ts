/**
 * The design system every b-roll composition draws from.
 *
 * This file exists because the previous approach had no design system at all:
 * an LLM authored fresh animation code per graphic, so each clip invented its
 * own type scale, spacing and rhythm. Measured on the shipped output, content
 * filled 26-29% of the panel and clips froze for up to 80% of their runtime.
 * Those are not prompt failures, they are the absence of a system.
 *
 * Everything here is derived from the CANVAS, not hardcoded, so the same
 * components hold up whether they render into the 1080x998 content panel or a
 * full 1080x1920 frame.
 */

export type Palette = string[];

export type BaseProps = {
  /** Source-derived palette, background first. */
  palette: Palette;
  width: number;
  height: number;
  durationInSeconds: number;
};

const LUMA = (hex: string): number => {
  const h = hex.replace('#', '');
  if (h.length !== 6) return 0;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return r * 0.299 + g * 0.587 + b * 0.114;
};

/**
 * An accent that reads as an accent.
 *
 * Taking palette[2] unconditionally painted a near-black highlight on the
 * annotate clip and an invisible rule on the thumbnail: a palette's leading
 * entries are the source's background and body colours. Mid-luminance only,
 * with amber as the fallback because it reads on any background.
 */
export const accentOf = (palette: Palette, fallback = '#FFD43B'): string => {
  for (let i = palette.length - 1; i >= 0; i--) {
    const c = palette[i];
    if (typeof c === 'string' && /^#[0-9a-f]{6}$/i.test(c)) {
      const l = LUMA(c);
      if (l > 70 && l < 210) return c;
    }
  }
  return fallback;
};

export const bgOf = (palette: Palette): string =>
  palette?.[0] && /^#[0-9a-f]{6}$/i.test(palette[0]) ? palette[0] : '#0B0D11';

export const inkOf = (palette: Palette): string => {
  const bg = bgOf(palette);
  return LUMA(bg) > 140 ? '#0B0D11' : '#F4F6F8';
};

/**
 * Type scale as a fraction of canvas HEIGHT.
 *
 * Sizes are relative because the failure mode was absolute: type chosen against
 * a desktop preview is illegible in a panel that occupies half a phone screen.
 * The floor is the number that matters — 4% of 998px is 40px, and nothing in a
 * composition may go below it.
 */
export const typeScale = (height: number) => ({
  solo: height * 0.42, // one figure or one word, dominating the frame
  hero: height * 0.15,
  title: height * 0.085,
  body: height * 0.055,
  label: height * 0.042,
  floor: height * 0.04,
  mono: height * 0.046,
});

export const spacing = (height: number) => ({
  pad: height * 0.06,
  gap: height * 0.035,
  radius: height * 0.022,
});

export const FONT_CSS = `
@font-face{font-family:'Inter';src:url('/fonts/Inter-Regular.ttf') format('truetype');font-weight:400;font-display:block}
@font-face{font-family:'Inter';src:url('/fonts/Inter-SemiBold.ttf') format('truetype');font-weight:600;font-display:block}
@font-face{font-family:'Inter';src:url('/fonts/Inter-Bold.ttf') format('truetype');font-weight:700;font-display:block}
@font-face{font-family:'Inter';src:url('/fonts/Inter-Black.ttf') format('truetype');font-weight:900;font-display:block}
`;

export const SANS = "'Inter', system-ui, -apple-system, sans-serif";
export const MONO = "'JetBrains Mono', 'SFMono-Regular', Menlo, monospace";

/**
 * Shrink a display size until the string actually fits the canvas width.
 *
 * The type scale is derived from HEIGHT, which is right for vertical presence
 * and silently wrong for long strings: "10-15x" at 42% of a 998px canvas is 419px
 * tall and about 1460px wide, so the first render clipped it to "10-1". Height
 * alone can never catch that — the constraint is two-dimensional.
 *
 * `ratio` is the average glyph advance as a fraction of font size: Inter Black
 * numerals sit near 0.60, mixed-case text nearer 0.52. Deliberately slightly
 * generous, because clipping is a broken frame while a marginally smaller hero
 * is just a hero.
 */
export const fitToWidth = (
  text: string,
  maxSize: number,
  availableWidth: number,
  ratio = 0.6,
): number => {
  const chars = Math.max(1, text.length);
  return Math.min(maxSize, availableWidth / (chars * ratio));
};

/**
 * Fit by the LONGEST WORD, not the whole string.
 *
 * Wrapped text breaks at spaces, so the binding constraint is the widest single
 * word — a headline can wrap to three lines happily and still clip if one word
 * is too wide for the column. This is what clipped "shadowbanning" to
 * "shadowba" while the overall character count looked comfortable.
 */
export const fitLongestWord = (
  text: string,
  maxSize: number,
  availableWidth: number,
  ratio = 0.54,
): number => {
  const longest = text
    .split(/\s+/)
    .reduce((a, b) => (b.length > a.length ? b : a), '');
  return fitToWidth(longest || text, maxSize, availableWidth, ratio);
};

/**
 * A SECOND accent, distinct from the first, for the backdrop's other orb and
 * for gradient stops. Falls back to a hue-shifted version of the primary so a
 * two-colour palette still yields a two-colour field rather than a flat wash.
 */
export const accent2Of = (palette: Palette): string => {
  const primary = accentOf(palette);
  const mids = (palette || []).filter((c) => {
    if (!/^#[0-9a-f]{6}$/i.test(c) || c.toLowerCase() === primary.toLowerCase()) return false;
    const l = LUMA(c);
    return l > 55 && l < 220;
  });
  if (mids.length) return mids[0];
  // Rotate the primary's channels: cheap, deterministic, always distinct.
  const h = primary.replace('#', '');
  return `#${h.slice(2, 4)}${h.slice(4, 6)}${h.slice(0, 2)}`;
};
