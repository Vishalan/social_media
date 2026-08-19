import React from 'react';
import {AbsoluteFill} from 'remotion';
import {evolvePath} from '@remotion/paths';
import {useClip} from '../lib/timing';
import {ramp, pop, wipe} from '../lib/motion';
import {Aurora, PulseRings} from '../lib/atmosphere';
import {FONT_CSS, SANS, MONO, typeScale, spacing, accentOf, accent2Of,
        bgOf, inkOf, Palette} from '../theme';
import {fitBlock, fitOneLine} from '../lib/fit';

export type FlowSceneProps = {
  palette: Palette;
  title?: string;
  /** Stages the thing passes through. 3-5. */
  stages: string[];
  /** What comes out at the end. */
  result?: string;
  /** What goes in at the top. */
  input?: string;
};

/**
 * A pipeline drawn as an actual diagram: nodes, connectors that DRAW
 * themselves, and a token travelling down the path.
 *
 * This is the composition the set was missing. Everything else here — even
 * Mechanism, which is a numbered list in boxes — communicates a process by
 * describing it in words. A flow is the one idea that a diagram states and a
 * sentence only approximates, and "posts go through these stages and some do
 * not come out" is exactly that idea.
 *
 * The connector uses evolvePath from @remotion/paths: an SVG stroke revealed by
 * animating strokeDasharray, so the line is DRAWN between nodes rather than
 * fading in. A dot then travels the same bezier, which is what makes it read as
 * flow rather than as a static chart.
 */
export const FlowScene: React.FC<FlowSceneProps> = ({
  palette, title, stages, result, input,
}) => {
  const {t, frame, fps, width, height, durationInFrames} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const ink = inkOf(palette);

  const nodes = (stages || []).filter(Boolean).slice(0, 5);
  const n = Math.max(1, nodes.length);

  // Layout, measured rather than guessed.
  //
  // The first version multiplied magic fractions together — nodeH from one
  // fraction, spacing from another — and the nodes overlapped each other AND
  // their own text. Every quantity here is now derived from the space that is
  // actually left after the fixed furniture is accounted for, and the node
  // labels are fitted to ONE line so a node can never grow past its box.
  const nodeW = width - s.pad * 2;
  const cx = width / 2;

  const titleH = title ? ty.label * 1.6 : 0;
  const inputH = input ? ty.body * 1.3 : 0;
  // The banner's reserved height and its DRAWN height were computed
  // independently and disagreed, so the banner sat on top of the last node.
  // Now one is derived from the other: fix the text budget to two lines at a
  // known size, and the reservation is exactly that plus the real padding.
  const resultPadY = height * 0.022;
  const resultMax = ty.body * 0.95;
  const resultTextH = resultMax * 1.12 * 2;              // hard two-line cap
  const resultH = result ? resultTextH + resultPadY * 2 + s.pad : 0;
  const avail = Math.max(1, height - s.pad * 2 - titleH - inputH - resultH);

  // Each node owns a slot; the box fills 62% of it, leaving the rest as the
  // gap the connector is drawn through. That single ratio is what guarantees
  // boxes cannot touch.
  const slot = avail / n;
  const nodeH = Math.min(slot * 0.62, height * 0.085);
  const label = Math.max(ty.floor * 0.8, Math.min(ty.body * 0.8, nodeH * 0.42));
  const top = s.pad + titleH + inputH;

  const centreY = (i: number) => top + slot * i + slot / 2;
  // Build times: each node lands, then its connector draws to the next.
  const nodeAt = (i: number) => 0.06 + (0.55 / n) * i;

  return (
    <AbsoluteFill style={{background: bgOf(palette), fontFamily: SANS}}>
      <style>{FONT_CSS}</style>
      <Aurora palette={palette} opacity={0.26} />
      <PulseRings palette={palette} count={3} speed={0.45} y="18%" maxFrac={1.6} />

      {/* Connectors, drawn under the nodes. */}
      <AbsoluteFill>
        <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
          {nodes.slice(0, -1).map((_, i) => {
            const y1 = centreY(i) + nodeH / 2;
            const y2 = centreY(i + 1) - nodeH / 2;
            const path = `M ${cx} ${y1} C ${cx} ${y1 + (y2 - y1) * 0.5}, `
              + `${cx} ${y2 - (y2 - y1) * 0.5}, ${cx} ${y2}`;
            const p = ramp(t, nodeAt(i) + 0.02, nodeAt(i + 1));
            const ev = evolvePath(p, path);
            // A token riding the same path, so the eye follows the direction.
            const tokenP = ((frame / Math.max(1, fps) * 0.55) % 1);
            const ty2 = y1 + (y2 - y1) * tokenP;
            return (
              <g key={i}>
                <path
                  d={path}
                  stroke={acc}
                  strokeWidth={Math.max(2, height * 0.0035)}
                  fill="none"
                  strokeDasharray={ev.strokeDasharray}
                  strokeDashoffset={ev.strokeDashoffset}
                  opacity={0.85}
                />
                {p > 0.98 ? (
                  <circle cx={cx} cy={ty2} r={Math.max(3, height * 0.006)}
                          fill={acc2} opacity={0.9} />
                ) : null}
              </g>
            );
          })}
        </svg>
      </AbsoluteFill>

      <AbsoluteFill style={{padding: s.pad}}>
        {title ? (
          <div style={{
            fontSize: fitOneLine(title.toUpperCase(), ty.label,
                                 width - s.pad * 2, 800, '0.16em'),
            fontWeight: 800, letterSpacing: '0.16em', whiteSpace: 'nowrap',
            textTransform: 'uppercase', color: acc,
            clipPath: wipe(ramp(t, 0, 0.08), 'left'),
          }}>{title}</div>
        ) : null}

        {input ? (
          <div style={{
            marginTop: s.gap * 0.25,
            fontSize: fitOneLine(input, ty.body * 0.8, width - s.pad * 2, 700, '0em'),
            fontWeight: 700, whiteSpace: 'nowrap',
            color: `${ink}AA`, opacity: ramp(t, 0.02, 0.12),
          }}>{input}</div>
        ) : null}

        {nodes.map((stage, i) => {
          const p = ramp(t, nodeAt(i), nodeAt(i) + 0.12);
          const sp = pop(frame, fps, Math.round(nodeAt(i) * durationInFrames));
          const last = i === n - 1;
          return (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: s.pad,
                top: centreY(i) - nodeH / 2,
                width: nodeW,
                height: nodeH,
                display: 'flex',
                alignItems: 'center',
                gap: label * 0.9,
                padding: `0 ${label}px`,
                borderRadius: s.radius,
                background: last ? `${acc}22` : `${ink}0E`,
                border: `2px solid ${last ? acc : `${ink}26`}`,
                boxShadow: `0 ${height * 0.008}px ${height * 0.03}px rgba(0,0,0,0.4)`,
                opacity: p,
                transform: `scale(${0.96 + 0.04 * sp})`,
                backdropFilter: 'blur(2px)',
              }}
            >
              <div style={{
                flex: '0 0 auto', width: label * 1.7, height: label * 1.7,
                borderRadius: 99, background: last ? acc : `${ink}22`,
                color: last ? '#0B0D11' : ink, fontWeight: 900,
                fontSize: label * 0.9, display: 'flex',
                alignItems: 'center', justifyContent: 'center',
              }}>{i + 1}</div>
              <div
                style={{
                  fontSize: fitOneLine(stage, label, nodeW - label * 4.2, 700, '0em'),
                  fontWeight: 700,
                  color: ink,
                  lineHeight: 1.15,
                  whiteSpace: 'nowrap',
                }}
              >
                {stage}
              </div>
            </div>
          );
        })}

        {result ? (
          <div style={{
            position: 'absolute', left: s.pad, right: s.pad, bottom: s.pad,
            padding: `${resultPadY}px ${s.gap}px`,
            borderRadius: s.radius,
            background: `linear-gradient(110deg, ${acc}, ${acc2})`,
            color: '#0B0D11', fontWeight: 900, lineHeight: 1.12,
            // Fit to the banner's own inner width, not the panel's. The first
            // version wrapped and spilled past the rounded corner.
            fontSize: fitBlock(result, resultMax,
                               width - s.pad * 2 - s.gap * 2,
                               resultTextH, {lineHeight: 1.12, fontWeight: 900}),
            clipPath: wipe(ramp(t, 0.66, 0.82)),
          }}>{result}</div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
