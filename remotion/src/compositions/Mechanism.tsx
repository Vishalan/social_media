import React from 'react';
import {Frame, Kicker} from '../lib/ui';
import {useClip, at, stagger} from '../lib/timing';
import {typeScale, spacing, accentOf, inkOf, Palette} from '../theme';

export type MechanismProps = {
  palette: Palette;
  title?: string;
  /** Ordered steps. Capped at 4 — see below. */
  steps: string[];
  /** What the flow produces. Lands last, in the accent. */
  result?: string;
};

/**
 * How a thing works: numbered steps flowing to a result.
 *
 * Steps are HARD CAPPED AT FOUR. The old version rendered seven rows of ~16px
 * monospace, which is unreadable in a half-panel on a phone — the type floor and
 * the row count are the same constraint seen from two directions, and the cap is
 * the honest way to enforce it. Four legible steps beat seven unreadable ones,
 * so extra steps are dropped rather than shrinking the type.
 */
export const Mechanism: React.FC<MechanismProps> = ({palette, title, steps, result}) => {
  const {t, height, width} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const ink = inkOf(palette);

  const shown = steps.filter(Boolean).slice(0, 4);
  const n = shown.length;
  // Budget the vertical space explicitly. The first version divided a guessed
  // fraction of the canvas among the rows and then appended the result pill
  // underneath, so on a four-step flow the pill was pushed off the bottom edge.
  // Everything that will be drawn has to come out of one budget.
  const budget = height - s.pad * 2 - (title ? ty.label * 2.6 : 0);
  const resultH = result ? budget * 0.24 : 0;
  const rowsH = budget - resultH - s.gap * (n + 1);
  const rowH = rowsH / Math.max(1, n);
  // Two lines of copy must fit inside a row, hence the 0.34 factor on half.
  const fontSize = Math.max(ty.floor, Math.min(ty.body, rowH * 0.30));

  return (
    <Frame palette={palette} >
      {title ? <Kicker text={title} palette={palette} /> : null}
      <div style={{display: 'flex', flexDirection: 'column', gap: s.gap * 0.55, width: '100%'}}>
        {shown.map((step, i) => {
          const p = stagger(t, i, n, {from: 0.1, to: 0.68});
          return (
            <div key={i} style={{opacity: p, transform: `translateX(${(1 - p) * -28}px)`}}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: s.gap * 0.6,
                  background: `${acc}14`,
                  border: `2px solid ${acc}55`,
                  borderRadius: s.radius,
                  padding: `${rowH * 0.2}px ${s.gap}px`,
                }}
              >
                <div
                  style={{
                    flex: '0 0 auto',
                    width: fontSize * 1.7,
                    height: fontSize * 1.7,
                    borderRadius: 99,
                    background: acc,
                    color: '#0B0D11',
                    fontWeight: 900,
                    fontSize: fontSize * 0.92,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  {i + 1}
                </div>
                <div style={{fontSize, fontWeight: 700, color: ink, lineHeight: 1.2}}>{step}</div>
              </div>
              {i < n - 1 ? (
                <div
                  style={{
                    width: 3,
                    height: rowH * 0.22,
                    background: acc,
                    opacity: 0.55,
                    marginLeft: s.gap + fontSize * 0.85,
                  }}
                />
              ) : null}
            </div>
          );
        })}
      </div>

      {result ? (
        <div
          style={{
            marginTop: s.gap,
            width: '100%',
            opacity: at(t, 0.72, 0.9),
            transform: `translateY(${(1 - at(t, 0.72, 0.9)) * 22}px)`,
          }}
        >
          <div
            style={{
              background: acc,
              color: '#0B0D11',
              borderRadius: s.radius,
              padding: `${resultH * 0.22}px ${s.gap}px`,
              fontSize: Math.max(ty.floor, Math.min(ty.body * 1.05, resultH * 0.34)),
              fontWeight: 900,
              lineHeight: 1.15,
            }}
          >
            {result}
          </div>
        </div>
      ) : null}
    </Frame>
  );
};
