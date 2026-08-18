import React from 'react';
import {Frame, Kicker, Support} from '../lib/ui';
import {useClip, at, drift} from '../lib/timing';
import {typeScale, accentOf, spacing, Palette} from '../theme';
import {fitOneLine} from '../lib/fit';

export type StatCardProps = {
  palette: Palette;
  /** The figure exactly as the source states it: "10-15x", "$4.2B", "97.5%". */
  value: string;
  support?: string;
  kicker?: string;
};

/**
 * One hard figure, at the largest type in the system.
 *
 * The old version rendered "10-15x" at roughly 90px in a 998px panel with the
 * numeral occupying about a quarter of the height. Here the figure is `solo`
 * (42% of canvas height) and the layout has nowhere else to put the weight.
 *
 * The count-up runs on the NUMERIC part only, so "10-15x" ticks its digits
 * while keeping its separator and unit — the previous counter animated the
 * whole string and produced nonsense intermediate frames like "7-11x".
 */
export const StatCard: React.FC<StatCardProps> = ({palette, value, support, kicker}) => {
  const {t, height, width} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  // Fit to BOTH axes: the height-derived size clipped '10-15x' to '10-1'.
  const heroSize = fitOneLine(value, ty.solo, width - s.pad * 2, 900, '-0.045em');

  const p = at(t, 0.1, 0.62);
  const parts = value.match(/^(\D*)([\d.,]+)(\s*[-–—]\s*)?([\d.,]+)?(.*)$/);

  const roll = (target: string) => {
    const n = parseFloat(target.replace(/,/g, ''));
    if (!isFinite(n)) return target;
    const cur = n * p;
    const decimals = (target.split('.')[1] || '').length;
    return cur.toFixed(decimals);
  };

  const body = parts
    ? (
        <>
          {parts[1]}
          {roll(parts[2])}
          {parts[3] ?? ''}
          {parts[4] ? roll(parts[4]) : ''}
          <span style={{color: acc}}>{parts[5]}</span>
        </>
      )
    : value;

  return (
    <Frame palette={palette}>
      {kicker ? <Kicker text={kicker} palette={palette} /> : null}
      <div
        style={{
          fontSize: heroSize,
          fontWeight: 900,
          lineHeight: 0.92,
          letterSpacing: '-0.045em',
          fontVariantNumeric: 'tabular-nums',
          transform: `scale(${0.9 + 0.1 * p})`,
          transformOrigin: 'left center',
        }}
      >
        {body}
      </div>
      {/* The rule grows with the count and keeps easing after it lands. */}
      <div
        style={{
          height: height * 0.014,
          width: `${28 + 62 * at(t, 0.2, 0.95)}%`,
          background: acc,
          borderRadius: 99,
          marginTop: height * 0.035,
        }}
      />
      {support ? <Support text={support} palette={palette} from={0.5} /> : null}
    </Frame>
  );
};
