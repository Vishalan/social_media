import React from 'react';
import {Frame} from '../lib/ui';
import {useClip, at, stagger, blink} from '../lib/timing';
import {ramp, wipe} from '../lib/motion';
import {typeScale, spacing, accentOf, Palette, MONO} from '../theme';

export type CodeWalkthroughProps = {
  palette: Palette;
  filename?: string;
  /** Lines, optionally prefixed "+ " or "- " for diff colouring. */
  lines: string[];
  caption?: string;
};

/**
 * An editor pane with lines arriving one at a time.
 *
 * Capped at 7 lines and the type is floored, for the same reason Mechanism caps
 * steps: a pane that fits everything by shrinking is a pane nobody can read.
 */
export const CodeWalkthrough: React.FC<CodeWalkthroughProps> = ({
  palette,
  filename,
  lines,
  caption,
}) => {
  const {t, frame, fps, height} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);

  const shown = lines.filter(Boolean).slice(0, 7);
  const n = shown.length;
  const size = Math.max(ty.floor, Math.min(ty.mono, (height * 0.52) / Math.max(4, n) * 0.5));

  return (
    <Frame palette={palette} >
      <div
        style={{
          width: '100%',
          borderRadius: s.radius,
          overflow: 'hidden',
          border: `2px solid ${acc}44`,
          background: '#0D1117',
          boxShadow: `0 ${height * 0.016}px ${height * 0.06}px rgba(0,0,0,0.55)`,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: size * 0.6,
            padding: `${size * 0.7}px ${size}px`,
            background: '#161B22',
          }}
        >
          {['#FF5F56', '#FFBD2E', '#27C93F'].map((c) => (
            <div key={c} style={{width: size * 0.55, height: size * 0.55, borderRadius: 99, background: c}} />
          ))}
          {filename ? (
            <div style={{fontFamily: MONO, fontSize: size * 0.85, color: '#8B949E', marginLeft: size * 0.5}}>
              {filename}
            </div>
          ) : null}
        </div>
        <div style={{padding: size, display: 'flex', flexDirection: 'column', gap: size * 0.42}}>
          {shown.map((line, i) => {
            const p = stagger(t, i, n, {from: 0.08, to: 0.7});
            const add = line.startsWith('+');
            const del = line.startsWith('-');
            return (
              <div
                key={i}
                style={{
                  fontFamily: MONO,
                  fontSize: size,
                  lineHeight: 1.35,
                  color: add ? '#7EE787' : del ? '#FF7B72' : '#C9D1D9',
                  background: add ? '#2EA04326' : del ? '#F8514926' : 'transparent',
                  borderLeft: `3px solid ${add ? '#2EA043' : del ? '#F85149' : 'transparent'}`,
                  paddingLeft: size * 0.5,
                  clipPath: wipe(p, 'left'),
                  transform: `translateX(${(1 - p) * -10}px)`,
                  whiteSpace: 'pre',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {line}
              </div>
            );
          })}
          <div style={{fontFamily: MONO, fontSize: size, color: acc, opacity: blink(frame, fps)}}>_</div>
        </div>
      </div>
      {caption ? (
        <div
          style={{
            marginTop: s.gap * 0.8,
            fontSize: Math.max(ty.floor, ty.body * 0.92),
            fontWeight: 700,
            opacity: at(t, 0.72, 0.92),
          }}
        >
          {caption}
        </div>
      ) : null}
    </Frame>
  );
};
