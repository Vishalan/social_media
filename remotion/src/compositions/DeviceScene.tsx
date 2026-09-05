import React from 'react';
import {AbsoluteFill, interpolate, Easing} from 'remotion';
import {useClip} from '../lib/timing';
import {World, slowPush, At} from '../lib/stage';
import {typeScale, spacing, accentOf, accent2Of, inkOf, bgOf, Palette,
        groundOf, onGround, objectShadow} from '../theme';
import {SANS, MONO, FONT_CSS} from '../theme';
import {ramp} from '../lib/motion';
import {fitOneLine} from '../lib/fit';

export type FeedItem = {
  /** Short line of post text. */
  text: string;
  /** Optional score badge — the number the algorithm assigned. */
  score?: string;
  /** Draw this one as the promoted/demoted example. */
  mark?: 'up' | 'down';
};

export type DeviceSceneProps = {
  palette: Palette;
  /** Label above the phone. */
  title?: string;
  /** App name in the status bar. */
  app?: string;
  items: FeedItem[];
};

/**
 * A phone, running the thing the story is about.
 *
 * The counterpart to TerminalScene: that one shows the code, this shows what
 * the code DOES. For any story about a feed, a ranking, a recommendation or an
 * app change, the honest illustration is the surface the viewer already knows —
 * a phone with posts in it — not a card that says "your feed is ranked".
 *
 * The depth is a multiplane rig, per shotcraft: three layers driven off one
 * displacement at 0.35 / 0.7 / 1.4. The gradient has to be at least 2x between
 * neighbours or the eye reads them as one plane, and the far and near layers
 * carry blur so the separation is legible as depth rather than as loose cards
 * drifting. The phone itself is the middle layer and is never blurred, because
 * it is the layer being read.
 */
export const DeviceScene: React.FC<DeviceSceneProps> = ({
  palette,
  title,
  app,
  items,
}) => {
  const {t, frame, height, width, durationInFrames} = useClip();
  const ty = typeScale(height);
  const s = spacing(height);
  const acc = accentOf(palette);
  const acc2 = accent2Of(palette);
  const ink = inkOf(palette);

  // Phone geometry: tall enough to read as a phone, small enough that the
  // camera has somewhere to push from.
  // The height coefficient was tuned against the full 1920 frame, so in a
  // ~998 panel it produced a phone barely a third of the frame wide and rows
  // too small to read at arm's length. Readability is the whole reason this
  // composition exists, so the phone claims as much width as it can while
  // still leaving room for its own rows.
  const phoneW = Math.min(width * 0.62, height * 0.46);
  const bezel = phoneW * 0.035;
  const cx = width / 2;
  // Centre the whole block — title plus phone — not the phone alone.
  const cy = height / 2;

  const body = Math.min(ty.body * 0.62, phoneW / 16);
  const cardPad = phoneW * 0.055;

  // The phone is as tall as what is IN it. A fixed 2.05 aspect left roughly
  // 40% of the screen blank whenever the planner returned three rows instead
  // of four, and a phone with a large empty area below the content reads as a
  // half-loaded app rather than as a feed.
  const statusH = phoneW * 0.14;
  // A row's real height, summed from what it draws: its own padding, the
  // avatar line, the gap, and two lines of wrapped text.
  const rowH = cardPad * 1.44 + body * 1.9 + cardPad * 0.5 + body * 1.32 * 2;
  const gap = cardPad * 0.72;

  // How many rows FIT, rather than how many were supplied. Clamping the phone
  // height instead cut the last card in half, and half a card reads as a
  // rendering fault; three whole rows say the same thing and look deliberate.
  // The title shares the column with the phone, so the phone's budget is what
  // is left AFTER it. Sizing the phone against the full frame and then adding
  // a title on top pushed the title clean off the panel's upper edge — the
  // same overflow that `safe center` fixed in Frame, which this composition
  // does not use because it draws its own world.
  const titleBlockH = title ? ty.label * 1.5 + phoneW * 0.09 : 0;
  const room = height * 0.62 - titleBlockH - statusH - cardPad * 2;
  const fitRows = Math.max(1, Math.floor((room + gap) / (rowH + gap)));
  const rowCount = Math.min(items.length, 4, fitRows);
  const phoneH = statusH + cardPad * 2 + rowH * rowCount + gap * (rowCount - 1);

  // One displacement drives every plane.
  const drive = interpolate(t, [0, 1], [0, 140], {easing: Easing.inOut(Easing.quad)});

  const stops = slowPush(durationInFrames, cx, cy, 1.13);

  const rows = items.slice(0, rowCount);

  return (
    <AbsoluteFill style={{background: groundOf(palette), fontFamily: SANS, color: onGround(palette)}}>
      <style>{FONT_CSS}</style>

      {/* FAR plane: an atmospheric wash that moves least. */}
      <AbsoluteFill
        style={{
          transform: `translateX(${-drive * 0.35}px)`,
          filter: 'blur(2px) saturate(0.92)',
          opacity: 0.85,
          background:
            `radial-gradient(60% 40% at 22% 18%, ${acc}22, transparent 60%),` +
            `radial-gradient(50% 36% at 82% 76%, ${acc2}1E, transparent 62%)`,
        }}
      />

      <World frame={frame} stops={stops} width={width} height={height} trail={false}>
        {/* MID plane: the phone. Never blurred — this is what is being read. */}
        <At x={cx} y={cy}>
          {/* The phone is the SUBJECT and stays pinned. shotcraft is explicit
              that in a depth rig the read layer takes no transform of its own
              — parallax is the far and near planes moving AROUND it. Driving
              the subject too slid the phone a hundred-odd pixels off centre
              and left the frame lopsided. */}
          <div>
            {title ? (
              <div
                style={{
                  marginBottom: phoneW * 0.09,
                  textAlign: 'center',
                  fontSize: fitOneLine(title.toUpperCase(), ty.label, phoneW * 1.5, 800, '0.16em'),
                  fontWeight: 800,
                  letterSpacing: '0.16em',
                  whiteSpace: 'nowrap',
                  color: acc,
                  opacity: ramp(t, 0, 0.1),
                }}
              >
                {title}
              </div>
            ) : null}

            <div
              style={{
                width: phoneW,
                height: phoneH,
                borderRadius: phoneW * 0.13,
                background: '#0A0D12',
                border: `${bezel}px solid #171C24`,
                boxShadow: objectShadow(height, palette),
                overflow: 'hidden',
                position: 'relative',
              }}
            >
              {/* Status bar + notch, so it reads as a phone at a glance. */}
              <div
                style={{
                  height: statusH,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  position: 'relative',
                  borderBottom: '1px solid #171C24',
                }}
              >
                <div
                  style={{
                    position: 'absolute',
                    top: statusH * 0.19,
                    width: phoneW * 0.3,
                    height: statusH * 0.24,
                    borderRadius: 99,
                    background: '#000',
                  }}
                />
                <div
                  style={{
                    fontSize: body * 0.82,
                    fontWeight: 700,
                    color: '#6E7C8D',
                    marginTop: statusH * 0.30,
                  }}
                >
                  {/* The planner cheerfully returns the same string for
                      both; printing it twice in one frame looks like a bug. */}
                  {app && app.toLowerCase() !== (title ?? '').toLowerCase()
                    ? app
                    : ''}
                </div>
              </div>

              {/* The feed. Each card arrives in order, and the marked one gets
                  its badge after it has settled, so the eye reads the post
                  first and the verdict second. */}
              <div style={{padding: cardPad, display: 'flex', flexDirection: 'column', gap}}>
                {rows.map((it, i) => {
                  const a = ramp(t, 0.10 + i * 0.11, 0.24 + i * 0.11);
                  const badge = ramp(t, 0.34 + i * 0.11, 0.46 + i * 0.11);
                  const edge = it.mark === 'up' ? acc2 : it.mark === 'down' ? '#F5A524' : '#222A35';
                  return (
                    <div
                      key={i}
                      style={{
                        background: '#11161D',
                        border: `1px solid ${edge}`,
                        borderLeft: `${phoneW * 0.014}px solid ${it.mark ? edge : '#222A35'}`,
                        borderRadius: phoneW * 0.045,
                        padding: cardPad * 0.72,
                        opacity: a,
                        transform: `translateY(${(1 - a) * body * 1.2}px)`,
                      }}
                    >
                      <div style={{display: 'flex', alignItems: 'center', gap: cardPad * 0.5}}>
                        <div
                          style={{
                            width: body * 1.9,
                            height: body * 1.9,
                            borderRadius: 99,
                            background: `linear-gradient(135deg, ${acc}, ${acc2})`,
                            flexShrink: 0,
                            opacity: 0.85,
                          }}
                        />
                        <div style={{flex: 1}}>
                          <div
                            style={{
                              height: body * 0.5,
                              width: '48%',
                              borderRadius: 99,
                              background: '#222A35',
                            }}
                          />
                        </div>
                        {it.score ? (
                          <div
                            style={{
                              fontFamily: MONO,
                              fontSize: body * 0.86,
                              fontWeight: 800,
                              color: it.mark === 'down' ? '#F5A524' : acc2,
                              opacity: badge,
                              transform: `scale(${0.8 + 0.2 * badge})`,
                            }}
                          >
                            {it.score}
                          </div>
                        ) : null}
                      </div>
                      <div
                        style={{
                          marginTop: cardPad * 0.5,
                          fontSize: body,
                          fontWeight: 600,
                          lineHeight: 1.32,
                          color: '#C9D4E0',
                        }}
                      >
                        {it.text}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </At>
      </World>

      {/* NEAR plane: soft foreground shapes grazing the lens. Blurred and
          moving fastest, so they read as "in front of" rather than as debris. */}
      <AbsoluteFill
        style={{
          transform: `translateX(${-drive * 1.4}px)`,
          filter: 'blur(3px)',
          opacity: 0.9,
          pointerEvents: 'none',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: -width * 0.12,
            top: height * 0.14,
            width: width * 0.22,
            height: width * 0.22,
            borderRadius: 99,
            background: `${acc}14`,
          }}
        />
        <div
          style={{
            position: 'absolute',
            right: -width * 0.16,
            bottom: height * 0.1,
            width: width * 0.3,
            height: width * 0.3,
            borderRadius: 99,
            background: `${acc2}12`,
          }}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
