import React from 'react';
import {Frame, Kicker, Card} from '../lib/ui';
import {useClip} from '../lib/timing';
import {ramp, pop, wipe} from '../lib/motion';
import {typeScale, spacing, accentOf, accent2Of, inkOf, Palette} from '../theme';
import {fitWrapped} from '../lib/fit';

export type SplitScreenProps = {
  /** The SUBJECT's mark — see broll_director.render_designed. */
  icon?: string;
  palette: Palette;
  kicker?: string;
  left: {label: string; value: string};
  right: {label: string; value: string};
};

/**
 * Two comparables as facing cards, with the divider drawing between them.
 *
 * The right side is the one that carries the accent: in every comparison this
 * type is used for — open vs closed, before vs after — the second panel is the
 * point being made, so it should be the one that reads first.
 */
export const SplitScreen: React.FC<SplitScreenProps> = ({palette, icon, kicker, left, right}) => {
  const {t, frame, fps, height, width, durationInFrames} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const ink = inkOf(palette);

  const colW = (width - s.pad * 2) / 2 - s.gap;
  // The smaller of the two, so a comparison never implies a hierarchy through
  // mismatched type sizes.
  const valueSize = Math.min(
    fitWrapped(left.value, ty.hero * 1.05, colW * 0.86),
    fitWrapped(right.value, ty.hero * 1.05, colW * 0.86),
  );
  const divider = ramp(t, 0.14, 0.5);

  const Col: React.FC<{d: {label: string; value: string}; delay: number; tint: string; tone: 'neutral' | 'accent'}> =
    ({d, delay, tint, tone}) => {
      const p = ramp(t, delay, delay + 0.22);
      const sp = pop(frame, fps, Math.round(delay * durationInFrames));
      return (
        <Card
          palette={palette}
          tone={tone}
          p={p}
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            gap: s.gap * 0.45,
            minHeight: height * 0.46,
            transform: `translateY(${(1 - sp) * 26}px) scale(${0.97 + 0.03 * sp})`,
          }}
        >
          <div
            style={{
              fontSize: ty.label,
              fontWeight: 800,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: tint,
            }}
          >
            {d.label}
          </div>
          <div
            style={{
              fontSize: valueSize,
              fontWeight: 900,
              lineHeight: 1.0,
              color: ink,
              letterSpacing: '-0.03em',
              clipPath: wipe(p),
            }}
          >
            {d.value}
          </div>
        </Card>
      );
    };

  return (
    <Frame palette={palette}>
      {kicker ? <Kicker text={kicker} palette={palette} icon={icon} /> : null}
      <div style={{display: 'flex', width: '100%', alignItems: 'stretch', gap: s.gap * 0.5}}>
        <Col d={left} delay={0.03} tint={`${ink}99`} tone="neutral" />
        <div
          style={{
            width: 4,
            alignSelf: 'center',
            height: `${divider * 82}%`,
            background: `linear-gradient(180deg, ${acc}, ${acc2})`,
            borderRadius: 99,
            boxShadow: `0 0 ${height * 0.03}px ${acc}88`,
          }}
        />
        <Col d={right} delay={0.18} tint={acc} tone="accent" />
      </div>
    </Frame>
  );
};
