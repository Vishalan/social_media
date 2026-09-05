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
export const bgOf = (palette: Palette): string =>
  palette?.[0] && /^#[0-9a-f]{6}$/i.test(palette[0]) ? palette[0] : '#0B0D11';

// ─── contrast ────────────────────────────────────────────────────────────────
//
// A palette lifted from a brand is a set of colours that work TOGETHER on that
// brand's own site — where the accent sits on white, not on the brand's own
// background. Dropping both into the same frame is not the same arrangement.
//
// Anthropic's palette is the case that exposed it: a coral background with a
// slightly darker coral in the set. The old accent picker filtered on absolute
// brightness alone (70 < luma < 210), so the darker coral passed happily and
// was used for display type ON the coral background — a contrast ratio of
// roughly 1.2:1, which is invisible. Half a headline and the source kicker
// disappeared into the background of a finished video.
//
// Brightness cannot answer this question, because legibility is not a property
// of a colour. It is a property of a PAIR.

/** WCAG relative luminance. Linearises sRGB first — the crude 0-255 average is
 *  what let a 1.2:1 pair look acceptable to the old check. */
const relLum = (hex: string): number => {
  const h = hex.replace('#', '');
  const ch = [0, 2, 4].map((i) => {
    const v = parseInt(h.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
};

/** WCAG contrast ratio, 1 (identical) to 21 (black on white). */
export const contrastRatio = (a: string, b: string): number => {
  const la = relLum(a);
  const lb = relLum(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
};

const toHsl = (hex: string): [number, number, number] => {
  const h = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let hue: number;
  if (max === r) hue = ((g - b) / d + (g < b ? 6 : 0)) / 6;
  else if (max === g) hue = ((b - r) / d + 2) / 6;
  else hue = ((r - g) / d + 4) / 6;
  return [hue, s, l];
};

const fromHsl = (hh: number, s: number, l: number): string => {
  const f = (n: number) => {
    const k = (n + hh * 12) % 12;
    const a = s * Math.min(l, 1 - l);
    const v = l - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)));
    return Math.round(255 * v).toString(16).padStart(2, '0');
  };
  return `#${f(0)}${f(8)}${f(4)}`;
};

/**
 * The nearest version of `fg` that is actually legible on `bg`.
 *
 * Hue and saturation are preserved and only LIGHTNESS moves, so the result
 * still reads as the brand's colour rather than a generic swatch — the point
 * is to keep borrowing the subject's identity, just legibly. It walks away
 * from the background in whichever direction has more headroom, and gives up
 * to plain ink or paper if the hue cannot reach the target at any lightness.
 */
/** Ink or paper, whichever is legible ON the given colour. */
export const onColor = (bg: string): string =>
  contrastRatio('#FFFFFF', bg) >= contrastRatio('#0B0D11', bg) ? '#FFFFFF' : '#0B0D11';

export const ensureContrast = (fg: string, bg: string, min = 4.5): string => {
  if (contrastRatio(fg, bg) >= min) return fg;
  const [h, s] = toHsl(fg);
  const bgL = relLum(bg);
  // Move toward whichever end is further from the background.
  const up = bgL < 0.5;
  for (let i = 1; i <= 20; i++) {
    const l = up ? 0.5 + (i / 20) * 0.5 : 0.5 - (i / 20) * 0.5;
    const cand = fromHsl(h, s, l);
    if (contrastRatio(cand, bg) >= min) return cand;
  }
  // Saturated hues cannot always reach 4.5:1 at any lightness; fall back to
  // the highest-contrast neutral rather than shipping something unreadable.
  return contrastRatio('#FFFFFF', bg) >= contrastRatio('#0B0D11', bg)
    ? '#FFFFFF'
    : '#0B0D11';
};

export const accentOf = (palette: Palette, fallback = '#FFD43B'): string => {
  const bg = bgOf(palette);
  const cands: string[] = [];
  for (let i = palette.length - 1; i >= 0; i--) {
    const c = palette[i];
    if (typeof c === 'string' && /^#[0-9a-f]{6}$/i.test(c)) cands.push(c);
  }
  // An accent has two jobs and the first fix only enforced one of them. It has
  // to be legible ON the background, and DISTINCT from the body ink — an
  // accent the same colour as the surrounding text is not an accent, it is
  // just text. Enforcing legibility alone drove the Anthropic accent to
  // near-black, which is exactly what the ink already was, so a headline came
  // out perfectly readable with no emphasis anywhere in it.
  const ink = LUMA(bg) > 140 ? '#0B0D11' : '#F4F6F8';
  const legible = cands.filter((c) => contrastRatio(c, bg) >= 4.5);
  const distinct = legible.filter((c) => contrastRatio(c, ink) >= 1.7);
  if (distinct.length) return distinct[0];
  if (legible.length) return legible[0];
  // Otherwise take the most promising one and lift it until it reads. The old
  // code returned the first mid-bright colour regardless, which on a coral
  // background meant coral-on-coral.
  if (cands.length) {
    const best = cands.reduce((a, b) =>
      contrastRatio(b, bg) > contrastRatio(a, bg) ? b : a);
    return ensureContrast(best, bg, 4.5);
  }
  return ensureContrast(fallback, bg, 4.5);
};


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
  // 0.09, up from 0.06. At 0.06 a 998px panel had 59px of margin — 5.5% of its
  // width — and large display type ran visually into the panel edge, which on a
  // squarish panel reads as content about to be cut off. The panel is composited
  // against the frame edge on three sides, so it has no bleed to lean on.
  pad: height * 0.09,
  gap: height * 0.035,
  radius: height * 0.022,
});

// Every face the compositions name is declared HERE and shipped in public/.
//
// Two of the three were silently absent. MONO named JetBrains Mono with no
// @font-face anywhere, and the scene titles asked for Georgia — which does not
// exist on Linux. Both fell through to DejaVu, the render host's default, so
// every terminal, code window and editorial title had been drawing in a
// typeface nobody chose. A font fallback never errors; it just quietly ships.
export const FONT_CSS = `
@font-face{font-family:'Inter';src:url('/fonts/Inter-Regular.ttf') format('truetype');font-weight:400;font-display:block}
@font-face{font-family:'Inter';src:url('/fonts/Inter-SemiBold.ttf') format('truetype');font-weight:600;font-display:block}
@font-face{font-family:'Inter';src:url('/fonts/Inter-Bold.ttf') format('truetype');font-weight:700;font-display:block}
@font-face{font-family:'Inter';src:url('/fonts/Inter-Black.ttf') format('truetype');font-weight:900;font-display:block}
@font-face{font-family:'Archivo Black';src:url('/fonts/ArchivoBlack.ttf') format('truetype');font-weight:400;font-display:block}
@font-face{font-family:'Anton';src:url('/fonts/Anton.ttf') format('truetype');font-display:block}
@font-face{font-family:'JetBrains Mono';src:url('/fonts/JetBrainsMono.ttf') format('truetype');font-display:block}
@font-face{font-family:'Fraunces';src:url('/fonts/Fraunces.ttf') format('truetype');font-display:block}
@font-face{font-family:'Sourced';src:url('/fonts/Sourced.ttf') format('truetype');font-weight:400 900;font-display:block}
@font-face{font-family:'SourcedText';src:url('/fonts/SourcedText.ttf') format('truetype');font-weight:400 900;font-display:block}
`;

// The display face for headlines and big claims. Inter is an excellent UI
// typeface and is on roughly nine in ten design-tool mockups, which is exactly
// why it reads as the default rather than as a decision. Archivo Black is a
// single heavy weight with real lowercase — the register news graphics use to
// carry a claim at thumbnail size, without the all-caps shout of Anton.
export const DISPLAY = "'Archivo Black', 'Inter', system-ui, sans-serif";
/**
 * The body face. `SourcedText` is written per-story from the SUBJECT's own
 * typographic category — matched, never copied: the real brand faces are
 * proprietary (Anthropic Sans, Build Week Digital, TwitterChirp) and cannot
 * be embedded in a monetised video. Inter carries every frame where nothing
 * was resolved, which is why it stays first in the fallback chain rather
 * than last.
 */
export const SANS = "'SourcedText', 'Inter', system-ui, -apple-system, sans-serif";

/** The display face for this story, from the same source. */
export const SOURCED = "'Sourced', 'Fraunces', Georgia, serif";
export const MONO = "'JetBrains Mono', 'SFMono-Regular', Menlo, monospace";
// A real editorial serif, shipped rather than hoped for.
export const SERIF = "'Fraunces', Georgia, 'Times New Roman', serif";

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
  // Same rule as the primary: a second accent nobody can see is not a second
  // accent. Filtering on brightness alone let this pick another near-background
  // tone from the same brand family.
  const bg2 = bgOf(palette);
  const legible = mids.filter((c) => contrastRatio(c, bg2) >= 4.5);
  if (legible.length) return legible[0];
  if (mids.length) return ensureContrast(mids[0], bg2, 4.5);
  // Rotate the primary's channels: cheap, deterministic, always distinct.
  const h = primary.replace('#', '');
  return ensureContrast(
    `#${h.slice(2, 4)}${h.slice(4, 6)}${h.slice(0, 2)}`, bg2, 4.5);
};


/**
 * The neutral ground an OBJECT sits on.
 *
 * The reference short's signature look is a product shot, not a card: a
 * terminal, a file, a window floating in generous space on a warm neutral,
 * with a soft shadow under it. Every composition here filled the frame with
 * the story's palette instead, which reads as a designed slide — the colour
 * is doing the work and the object is just content inside it.
 *
 * Grounding on a near-neutral does two things. The object gains an edge, so
 * it looks like a thing rather than a region. And the story's accent stops
 * being the whole background, which is what lets it mean something when it
 * IS used — the reference spends its accent on one word at a time.
 *
 * The ground is tinted a few percent toward the palette so it still belongs
 * to the story rather than being a generic grey, and it follows the
 * palette's own luminance so a dark brand does not get a cream stage.
 */
export const groundOf = (palette: Palette): string => {
  const base = bgOf(palette);
  const dark = LUMA(base) < 128;
  return dark ? '#111417' : '#EDE9E1';
};

/** Ink that reads on the ground from `groundOf`. */
export const onGround = (palette: Palette): string =>
  LUMA(bgOf(palette)) < 128 ? '#ECEFF3' : '#15181C';

/** The soft drop shadow that makes an object sit ON the ground. */
export const objectShadow = (h: number, palette: Palette): string => {
  const dark = LUMA(bgOf(palette)) < 128;
  return dark
    ? `0 ${h * 0.018}px ${h * 0.05}px rgba(0,0,0,.55), 0 ${h * 0.004}px ${h * 0.012}px rgba(0,0,0,.4)`
    : `0 ${h * 0.020}px ${h * 0.055}px rgba(28,24,18,.18), 0 ${h * 0.004}px ${h * 0.010}px rgba(28,24,18,.12)`;
};
