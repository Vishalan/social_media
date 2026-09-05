import React from 'react';
import {AbsoluteFill} from 'remotion';
import {useClip} from '../lib/timing';
import {World, slowPush, crashZoom, At} from '../lib/stage';
import {typeScale, spacing, accentOf, accent2Of, Palette, groundOf, objectShadow} from '../theme';
import {MONO, SANS, FONT_CSS} from '../theme';
import {fitOneLine} from '../lib/fit';

export type TerminalLine = {
  text: string;
  /** command = prompted and typed; out = program output; ok/warn = coloured. */
  kind?: 'command' | 'out' | 'ok' | 'warn';
};

export type TerminalSceneProps = {
  palette: Palette;
  /** Window title — normally the repo or working directory. */
  title?: string;
  lines: TerminalLine[];
  /** 0-based line index the camera punches in on at the end. */
  focusLine?: number;
};

/**
 * A terminal actually running something, shot with a camera.
 *
 * This exists because every other composition in this project is a card with
 * words on it. For a channel about software, the strongest available image of
 * software is software: a prompt, a command, and real output appearing under
 * it. It carries the same information a bulleted "how it works" card carries,
 * except the viewer recognises it instead of reading it.
 *
 * Two techniques are borrowed and both matter more than they look:
 *
 * The reveal is CHUNKED, not per-character. snapcn's terminal advances by
 * several characters every few frames, so output arrives in bursts the way a
 * real program prints it. A steady character drip is how a typewriter effect
 * looks, and nothing in a terminal has ever typed at a constant rate.
 *
 * The camera pushes in slowly while the output builds, then punches onto the
 * line that matters. Per shotcraft the push is on an accelerating curve and
 * barely perceptible at first; that is what makes the punch land.
 */
export const TerminalScene: React.FC<TerminalSceneProps> = ({
  palette,
  title,
  lines,
  focusLine,
}) => {
  const {frame, height, width, durationInFrames} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);

  // The window fills most of the world; the world is frame-sized so world
  // pixels and frame pixels agree at z=1 and the type stays legible.
  // Room around the object. The reference never runs its window to the
  // frame edge — the margin is what makes it read as a thing on a surface
  // rather than a panel that happens to have a border.
  const winW = width - s.pad * 3.2;
  // Lines are capped short by the director precisely so this can be large:
  // a terminal's readability is set by characters-per-line, and 24 is the most
  // that leaves the type comparable in size to the burned-in captions.
  const mono = Math.min(ty.body * 0.82, winW / 24);
  const lineH = mono * 1.62;
  const chromeH = mono * 2.5;

  // Chunked reveal. Each line waits for the one above to finish, commands are
  // slower than output because a person types them and a program does not.
  const startOf: number[] = [];
  const doneOf: number[] = [];
  let cursor = Math.round(durationInFrames * 0.06);
  lines.forEach((ln, i) => {
    const isCmd = (ln.kind ?? 'out') === 'command';
    const perChar = isCmd ? 1.15 : 0.32;
    startOf[i] = cursor;
    cursor += Math.max(6, Math.round(ln.text.length * perChar));
    doneOf[i] = cursor;
    cursor += isCmd ? 10 : 4;
  });

  const winH = chromeH + lineH * lines.length + mono * 2.2;
  const cx = width / 2;
  const cy = height / 2;

  // Camera: a slow push over the whole window, then a punch onto the payoff
  // line if one was named. Without a focus line it stays on the push, because
  // a punch that lands on nothing in particular is just a zoom.
  const focusY =
    focusLine != null && focusLine < lines.length
      ? cy - winH / 2 + chromeH + lineH * (focusLine + 0.5)
      : null;
  // Zoom bounds come from the geometry, not from taste. The window may never
  // render wider than the frame, so the ceiling is exactly the ratio between
  // them; the opening zoom is set below it to leave somewhere to push FROM.
  // Without this the punch cropped the left and right off every line.
  const zMax = (width * 0.99) / winW;
  const zOpen = zMax * 0.78;
  const stops =
    focusY == null
      ? slowPush(durationInFrames, cx, cy, zMax)
      : crashZoom(
          durationInFrames,
          {x: cx, y: cy},
          {x: cx, y: focusY},
          Math.round(durationInFrames * 0.62),
          {from: zOpen, to: zMax},
        );

  const colourOf = (kind: string) =>
    kind === 'ok' ? acc2 : kind === 'warn' ? '#F5A524' : kind === 'command' ? '#E8EDF4' : '#93A4B8';

  return (
    <AbsoluteFill style={{background: groundOf(palette), fontFamily: SANS}}>
      <style>{FONT_CSS}</style>
      {/* A faint wash so the window is lit rather than pasted on black. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(120% 80% at 50% 12%, ${acc}18, transparent 62%)`,
        }}
      />
      <World frame={frame} stops={stops} width={width} height={height}>
        <At x={cx} y={cy}>
          <div
            style={{
              width: winW,
              minHeight: winH,
              borderRadius: s.radius,
              background: 'linear-gradient(180deg, #0E1319, #0A0D12)',
              border: '1px solid #1E2733',
              boxShadow: objectShadow(height, palette),
              overflow: 'hidden',
            }}
          >
            {/* Chrome. The traffic lights are what make a rectangle read as a
                window without a caption saying "this is a terminal". */}
            <div
              style={{
                height: chromeH,
                display: 'flex',
                alignItems: 'center',
                gap: mono * 0.5,
                padding: `0 ${mono}px`,
                background: '#121821',
                borderBottom: '1px solid #1E2733',
              }}
            >
              {['#FF5F57', '#FEBC2E', '#28C840'].map((c) => (
                <div
                  key={c}
                  style={{width: mono * 0.62, height: mono * 0.62, borderRadius: 99, background: c}}
                />
              ))}
              {title ? (
                <div
                  style={{
                    marginLeft: mono * 0.8,
                    fontFamily: MONO,
                    fontSize: mono * 0.82,
                    color: '#7C8CA0',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {title}
                </div>
              ) : null}
            </div>

            <div style={{padding: `${mono}px ${mono}px ${mono * 1.2}px`}}>
              {lines.map((ln, i) => {
                if (frame < startOf[i]) return <div key={i} style={{height: lineH}} />;
                const kind = ln.kind ?? 'out';
                // Chunked: advance in steps rather than one character at a
                // time, so output lands in bursts like a real program's.
                const span = Math.max(1, doneOf[i] - startOf[i]);
                const p = Math.min(1, (frame - startOf[i]) / span);
                const chunk = kind === 'command' ? 1 : 3;
                const shown = Math.min(
                  ln.text.length,
                  Math.ceil((p * ln.text.length) / chunk) * chunk,
                );
                const typing = frame < doneOf[i];
                return (
                  <div
                    key={i}
                    style={{
                      height: lineH,
                      display: 'flex',
                      alignItems: 'center',
                      fontFamily: MONO,
                      fontSize: mono,
                      color: colourOf(kind),
                      whiteSpace: 'pre',
                      fontWeight: kind === 'command' ? 700 : 500,
                    }}
                  >
                    {kind === 'command' ? (
                      <span style={{color: acc, marginRight: mono * 0.5}}>❯</span>
                    ) : null}
                    <span>{ln.text.slice(0, shown)}</span>
                    {typing ? (
                      <span
                        style={{
                          display: 'inline-block',
                          width: mono * 0.55,
                          height: mono * 1.05,
                          marginLeft: 2,
                          background: acc,
                          opacity: Math.floor(frame / 8) % 2 ? 0.25 : 1,
                        }}
                      />
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        </At>
      </World>
    </AbsoluteFill>
  );
};
