import React from 'react';
import {Frame, Kicker, Card} from '../lib/ui';
import {useClip} from '../lib/timing';
import {ramp, pop, wipe} from '../lib/motion';
import {typeScale, spacing, accentOf, accent2Of, inkOf, Palette} from '../theme';

export type MechanismProps = {
  /** The SUBJECT's mark — see broll_director.render_designed. */
  icon?: string;
  palette: Palette;
  title?: string;
  steps: string[];
  result?: string;
};

/**
 * How a thing works: numbered steps flowing into a result.
 *
 * Steps are HARD CAPPED AT FOUR. Seven rows of small monospace is unreadable in
 * a half-panel on a phone; the type floor and the row count are one constraint
 * seen from two directions, so extra steps are dropped rather than shrinking
 * the type. Each row springs in and its connector draws down to the next, so
 * the flow reads as a sequence rather than a list appearing.
 */
export const Mechanism: React.FC<MechanismProps> = ({palette, icon, title, steps, result}) => {
  const {t, frame, fps, height, durationInFrames} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const ink = inkOf(palette);

  const shown = steps.filter(Boolean).slice(0, 4);
  const n = shown.length;
  // One budget for everything that will be drawn: appending the result pill to
  // a guessed row fraction pushed it off the bottom on a four-step flow.
  const budget = height - s.pad * 2 - (title ? ty.label * 2.8 : 0);
  const resultH = result ? budget * 0.24 : 0;
  const rowsH = budget - resultH - s.gap * (n + 1);
  const rowH = rowsH / Math.max(1, n);
  const fontSize = Math.max(ty.floor, Math.min(ty.body, rowH * 0.3));
  const window = 0.40 / Math.max(1, n);

  return (
    <Frame palette={palette}>
      {title ? <Kicker text={title} palette={palette} icon={icon} /> : null}
      <div style={{display: 'flex', flexDirection: 'column', width: '100%'}}>
        {shown.map((step, i) => {
          const start = 0.04 + window * i;
          const p = ramp(t, start, start + window * 1.5);
          const sp = pop(frame, fps, Math.round(start * durationInFrames));
          return (
            <div key={i} style={{width: '100%'}}>
              <Card
                palette={palette}
                tone="accent"
                p={p}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: s.gap * 0.6,
                  transform: `translateX(${(1 - sp) * -26}px) scale(${0.97 + 0.03 * sp})`,
                }}
              >
                <div
                  style={{
                    flex: '0 0 auto',
                    width: fontSize * 1.75,
                    height: fontSize * 1.75,
                    borderRadius: 99,
                    background: `linear-gradient(140deg, ${acc}, ${acc2})`,
                    color: '#0B0D11',
                    fontWeight: 900,
                    fontSize: fontSize * 0.95,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    boxShadow: `0 0 ${height * 0.035}px ${acc}77`,
                  }}
                >
                  {i + 1}
                </div>
                <div style={{fontSize, fontWeight: 700, color: ink, lineHeight: 1.2}}>{step}</div>
              </Card>
              {i < n - 1 ? (
                <div
                  style={{
                    width: 3,
                    height: rowH * 0.26 * ramp(t, start + window * 0.6, start + window * 1.4),
                    background: acc,
                    opacity: 0.6,
                    marginLeft: s.gap + fontSize * 0.9,
                    marginTop: s.gap * 0.25,
                    marginBottom: s.gap * 0.25,
                  }}
                />
              ) : null}
            </div>
          );
        })}
      </div>

      {result ? (
        <div style={{marginTop: s.gap * 0.9, width: '100%', clipPath: wipe(ramp(t, 0.44, 0.6))}}>
          <div
            style={{
              background: `linear-gradient(120deg, ${acc}, ${acc2})`,
              color: '#0B0D11',
              borderRadius: s.radius,
              padding: `${resultH * 0.22}px ${s.gap}px`,
              fontSize: Math.max(ty.floor, Math.min(ty.body * 1.05, resultH * 0.34)),
              fontWeight: 900,
              lineHeight: 1.15,
              boxShadow: `0 ${height * 0.012}px ${height * 0.05}px ${acc}44`,
            }}
          >
            {result}
          </div>
        </div>
      ) : null}
    </Frame>
  );
};
