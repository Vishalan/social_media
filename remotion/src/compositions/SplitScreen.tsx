import React from 'react';
import {Frame, Kicker} from '../lib/ui';
import {useClip, at} from '../lib/timing';
import {typeScale, spacing, accentOf, inkOf, Palette} from '../theme';
import {fitWrapped} from '../lib/fit';

export type SplitScreenProps = {
  palette: Palette;
  kicker?: string;
  left: {label: string; value: string};
  right: {label: string; value: string};
};

/**
 * Two comparables, side by side, with the divider drawing between them.
 *
 * The panel is roughly square, so the two halves are stacked as columns rather
 * than rows: a wide-short pair reads better across a squarish canvas, and it
 * lets each value take the full column width at large type.
 */
export const SplitScreen: React.FC<SplitScreenProps> = ({palette, kicker, left, right}) => {
  const {t, height, width} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const ink = inkOf(palette);

  // Each column gets roughly half the canvas, so fit both values to that and
  // use the SMALLER of the two: mismatched sizes across a comparison read as
  // a hierarchy that is not there.
  const colW = (width - spacing(height).pad * 2) / 2 - spacing(height).gap;
  const valueSize = Math.min(
    fitWrapped(left.value, ty.hero * 1.15, colW),
    fitWrapped(right.value, ty.hero * 1.15, colW),
  );
  const pL = at(t, 0.1, 0.42);
  const pR = at(t, 0.32, 0.66);
  const divider = at(t, 0.24, 0.8);

  const Col: React.FC<{d: {label: string; value: string}; p: number; tint: string}> = ({d, p, tint}) => (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        gap: s.gap * 0.5,
        opacity: p,
        transform: `translateY(${(1 - p) * 30}px)`,
        padding: s.gap * 0.6,
      }}
    >
      <div
        style={{
          fontSize: ty.label,
          fontWeight: 700,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: tint,
        }}
      >
        {d.label}
      </div>
      <div style={{fontSize: valueSize, fontWeight: 900, lineHeight: 0.98, color: ink, letterSpacing: '-0.03em'}}>
        {d.value}
      </div>
    </div>
  );

  return (
    <Frame palette={palette} align="start">
      {kicker ? <Kicker text={kicker} palette={palette} /> : null}
      <div style={{display: 'flex', width: '100%', flex: 1, alignItems: 'stretch'}}>
        <Col d={left} p={pL} tint={`${ink}99`} />
        <div
          style={{
            width: 4,
            alignSelf: 'center',
            height: `${divider * 88}%`,
            background: acc,
            borderRadius: 99,
            margin: `0 ${s.gap * 0.4}px`,
          }}
        />
        <Col d={right} p={pR} tint={acc} />
      </div>
    </Frame>
  );
};
