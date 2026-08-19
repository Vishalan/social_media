import React from 'react';
import {AbsoluteFill} from 'remotion';
import {useClip, blink} from '../lib/timing';
import {ramp, pop, settle, wipe} from '../lib/motion';
import {FONT_CSS, SANS, MONO, typeScale, spacing, accentOf, accent2Of, Palette} from '../theme';
import {fitBlock} from '../lib/fit';

export type WindowSceneProps = {
  palette: Palette;
  /** Editorial title, set in serif italic. 1-4 words. */
  title: string;
  /** The window's own chrome label, e.g. "the-algorithm — main". */
  windowTitle?: string;
  /** Content lines. Prefix "+ " / "- " for diff colouring. */
  lines: string[];
  /** Subject brand mark as a data URI — the thing the story is ABOUT. */
  icon?: string;
  /** Which chapter of the video this is, for the progress rail. */
  step?: number;
  steps?: number;
};

/**
 * An app window on a full-bleed brand field.
 *
 * Built from what the reference work actually does rather than from our own
 * habits. Three things separate it from a typography card:
 *
 * FULL-BLEED BRAND COLOUR, not a dark gradient. The reference scenes sit on a
 * saturated field taken from the subject's identity, which does more to say
 * "this is about X" than any amount of accent-coloured text.
 *
 * A REAL OBJECT as the hero. A window with chrome — traffic lights, a title
 * bar, a body — reads as a thing being shown, where a bordered <div> of text
 * reads as a slide. The content inside it can then be mundane and still work.
 *
 * A PROGRESS RAIL. Segmented, one cell per beat, filling as the video runs.
 * It costs nothing and gives every clip a sense of position in a sequence.
 */
export const WindowScene: React.FC<WindowSceneProps> = ({
  palette,
  title,
  windowTitle,
  lines,
  icon,
  step = 1,
  steps = 5,
}) => {
  const {t, frame, fps, width, height, durationInFrames} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);

  const shown = (lines || []).filter(Boolean).slice(0, 7);
  const n = Math.max(1, shown.length);

  const pTitle = ramp(t, 0.02, 0.26);
  const spTitle = settle(frame, fps, 0);
  const spWin = pop(frame, fps, Math.round(0.12 * durationInFrames));
  const winW = width * 0.86;
  // Fit the monospace body to the WINDOW's inner width, not to a guess. The
  // widest line is what decides: a path is one "word" and can still be twice
  // the window wide, which is how the first build clipped its lines.
  const longest = shown.reduce((a, b) => (b.length > a.length ? b : a), '');
  const innerW = width * 0.86 - ty.mono * 2.2;
  // 0.66, not 0.60: the measured advance of this monospace face is wider
  // than the nominal 0.6em, and at 0.60 the longest line still grazed the
  // window edge. Erring narrow costs nothing; erring wide clips a character.
  const byWidth = longest ? (innerW / longest.length) / 0.66 : ty.mono;
  const bodyFont = Math.max(
    ty.floor * 0.72,
    Math.min(ty.mono * 0.82, (height * 0.30) / n * 0.5, byWidth),
  );
  const titleSize = fitBlock(title, ty.hero * 1.15, width - s.pad * 2, height * 0.2,
    {lineHeight: 1.05, fontWeight: 700, letterSpacing: '-0.01em'});

  return (
    <AbsoluteFill style={{fontFamily: SANS, background: acc}}>
      <style>{FONT_CSS}</style>

      {/* Full-bleed brand field with a soft vertical falloff. */}
      <AbsoluteFill
        style={{
          background: `linear-gradient(170deg, ${acc} 0%, ${acc2}CC 120%)`,
        }}
      />
      <AbsoluteFill
        style={{background: 'radial-gradient(120% 80% at 50% 30%, #FFFFFF18, transparent 60%)'}}
      />

      <AbsoluteFill style={{padding: s.pad, display: 'flex', flexDirection: 'column'}}>
        {/* Editorial serif title, as in the reference scenes. */}
        <div
          style={{
            fontFamily: 'Georgia, "Times New Roman", serif',
            fontStyle: 'italic',
            fontWeight: 700,
            fontSize: titleSize,
            lineHeight: 1.05,
            color: '#FFFFFF',
            textShadow: `0 ${height * 0.006}px ${height * 0.03}px rgba(0,0,0,0.35)`,
            clipPath: wipe(pTitle),
            transform: `translateY(${(1 - spTitle) * 22}px)`,
            marginBottom: s.gap * 0.8,
          }}
        >
          {title}
        </div>

        {/* The window: a real object, with chrome. */}
        <div
          style={{
            width: winW,
            alignSelf: 'center',
            borderRadius: s.radius,
            overflow: 'hidden',
            background: '#0D1117',
            border: '1px solid rgba(255,255,255,0.14)',
            boxShadow: `0 ${height * 0.03}px ${height * 0.09}px rgba(0,0,0,0.45)`,
            transform: `translateY(${(1 - spWin) * 40}px) scale(${0.96 + 0.04 * spWin})`,
            opacity: ramp(t, 0.1, 0.3),
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: bodyFont * 0.6,
              padding: `${bodyFont * 0.75}px ${bodyFont}px`,
              background: '#161B22',
              borderBottom: '1px solid rgba(255,255,255,0.08)',
            }}
          >
            {['#FF5F56', '#FFBD2E', '#27C93F'].map((c) => (
              <div key={c} style={{width: bodyFont * 0.55, height: bodyFont * 0.55,
                                   borderRadius: 99, background: c}} />
            ))}
            {icon ? (
              <img src={icon} style={{width: bodyFont * 1.25, height: bodyFont * 1.25,
                                      borderRadius: bodyFont * 0.28, marginLeft: bodyFont * 0.5,
                                      objectFit: 'contain'}} />
            ) : null}
            {windowTitle ? (
              <span style={{fontFamily: MONO, fontSize: bodyFont * 0.9, color: '#8B949E'}}>
                {windowTitle}
              </span>
            ) : null}
          </div>

          <div style={{padding: bodyFont, display: 'flex', flexDirection: 'column',
                       gap: bodyFont * 0.45, minHeight: height * 0.30}}>
            {shown.map((line, i) => {
              const start = 0.18 + (0.32 / n) * i;
              const p = ramp(t, start, start + 0.32 / n * 1.6);
              const add = line.trim().startsWith('+');
              const del = line.trim().startsWith('-');
              return (
                <div
                  key={i}
                  style={{
                    fontFamily: MONO,
                    fontSize: bodyFont,
                    lineHeight: 1.4,
                    color: add ? '#7EE787' : del ? '#FF7B72' : '#C9D1D9',
                    background: add ? '#2EA04326' : del ? '#F8514926' : 'transparent',
                    borderLeft: `3px solid ${add ? '#2EA043' : del ? '#F85149' : 'transparent'}`,
                    paddingLeft: bodyFont * 0.5,
                    clipPath: wipe(p, 'left'),
                    whiteSpace: 'pre',
                    overflow: 'hidden',
                  }}
                >
                  {line}
                </div>
              );
            })}
            <span style={{fontFamily: MONO, fontSize: bodyFont, color: '#FFFFFF',
                          opacity: blink(frame, fps)}}>▌</span>
          </div>
        </div>

        {/* Segmented progress rail — position in the sequence, for free. */}
        <div style={{marginTop: 'auto', display: 'flex', gap: width * 0.008, width: '100%'}}>
          {Array.from({length: Math.max(1, steps)}).map((_, i) => (
            <div
              key={i}
              style={{
                flex: 1,
                height: height * 0.008,
                borderRadius: 99,
                background: i < step ? '#FFFFFF' : 'rgba(255,255,255,0.25)',
                transform: i === step - 1 ? `scaleX(${ramp(t, 0.1, 0.9)})` : undefined,
                transformOrigin: 'left center',
              }}
            />
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
