import React from 'react';
import {Frame, Kicker} from '../lib/ui';
import {useClip, at, stagger} from '../lib/timing';
import {typeScale, spacing, accentOf, accent2Of, inkOf, Palette} from '../theme';

export type ChartBar = {label: string; value: number; display?: string};
export type CinematicChartProps = {
  palette: Palette;
  kicker?: string;
  bars: ChartBar[];
};

/** Horizontal bars growing from a baseline. Capped at 4 for legibility. */
export const CinematicChart: React.FC<CinematicChartProps> = ({palette, kicker, bars}) => {
  const {t, height} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const ink = inkOf(palette);

  const shown = bars.slice(0, 4);
  const max = Math.max(...shown.map((b) => b.value), 1);
  const rowH = (height * 0.55) / Math.max(1, shown.length);
  const size = Math.max(ty.floor, Math.min(ty.body, rowH * 0.3));

  return (
    <Frame palette={palette} >
      {kicker ? <Kicker text={kicker} palette={palette} /> : null}
      <div style={{display: 'flex', flexDirection: 'column', gap: s.gap * 0.7, width: '100%'}}>
        {shown.map((b, i) => {
          // Bars grow until 0.88 rather than the default 0.72. A chart has no
          // secondary motion to fall back on once the bars land, and stopping
          // at 0.72 left 21% of the clip visually static.
          const p = stagger(t, i, shown.length, {from: 0.1, to: 0.88});
          const isMax = b.value === max;
          return (
            <div key={i} style={{display: 'flex', flexDirection: 'column', gap: size * 0.3}}>
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}>
                <span style={{fontSize: size, fontWeight: 700, color: `${ink}CC`}}>{b.label}</span>
                <span style={{fontSize: size * 1.25, fontWeight: 900, color: isMax ? acc : ink, opacity: p}}>
                  {b.display ?? Math.round(b.value * p).toLocaleString()}
                </span>
              </div>
              <div style={{height: rowH * 0.32, background: `${ink}18`, borderRadius: 99, overflow: 'hidden'}}>
                <div
                  style={{
                    height: '100%',
                    // Floor the bar so a small value still reads as a bar.
                    // At 1 against 13 the baseline rendered as a dot, which
                    // looks like a rendering fault rather than a small number.
                    width: `${Math.max((b.value / max) * 100, 7) * p}%`,
                    background: isMax ? `linear-gradient(90deg, ${acc}, ${acc2})` : `${ink}55`,
                    boxShadow: isMax ? `0 0 ${height * 0.035}px ${acc}66` : undefined,
                    borderRadius: 99,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </Frame>
  );
};
