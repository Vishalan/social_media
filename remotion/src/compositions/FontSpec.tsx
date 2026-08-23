import React from 'react';
import {AbsoluteFill} from 'remotion';

const CSS = `
@font-face{font-family:'Inter';src:url('/fonts/Inter-Black.ttf');font-weight:900;font-display:block}
@font-face{font-family:'ArchivoBlack';src:url('/fonts/ArchivoBlack.ttf');font-display:block}
@font-face{font-family:'Anton';src:url('/fonts/Anton.ttf');font-display:block}
@font-face{font-family:'Montserrat';src:url('/fonts/Montserrat.ttf');font-weight:800;font-display:block}
@font-face{font-family:'BebasNeue';src:url('/fonts/BebasNeue.ttf');font-display:block}
@font-face{font-family:'JetBrainsMono';src:url('/fonts/JetBrainsMono.ttf');font-display:block}
@font-face{font-family:'Fraunces';src:url('/fonts/Fraunces.ttf');font-display:block}
@font-face{font-family:'PlayfairDisplay';src:url('/fonts/PlayfairDisplay.ttf');font-display:block}
`;

const LINE = 'No code. A thousand stars a day.';

const FACES = [
  {name: 'Inter Black  — current', family: 'Inter', weight: 900, ls: '-0.03em'},
  {name: 'Archivo Black', family: 'ArchivoBlack', weight: 400, ls: '-0.02em'},
  {name: 'Anton', family: 'Anton', weight: 400, ls: '0em'},
  {name: 'Montserrat ExtraBold', family: 'Montserrat', weight: 800, ls: '-0.02em'},
  {name: 'Bebas Neue', family: 'BebasNeue', weight: 400, ls: '0.01em'},
];

export const FontSpec: React.FC = () => (
  <AbsoluteFill style={{background: '#0E1116', padding: 54, color: '#F2F5F9'}}>
    <style>{CSS}</style>
    <div style={{display: 'flex', flexDirection: 'column', gap: 30}}>
      {FACES.map((f) => (
        <div key={f.name}>
          <div style={{fontFamily: 'Inter', fontSize: 21, fontWeight: 900,
                       letterSpacing: '.14em', textTransform: 'uppercase',
                       color: '#FF8A3D', marginBottom: 8}}>{f.name}</div>
          <div style={{fontFamily: f.family, fontWeight: f.weight,
                       letterSpacing: f.ls, fontSize: 74, lineHeight: 1.02}}>
            {LINE}
          </div>
        </div>
      ))}
      <div style={{marginTop: 8, display: 'flex', gap: 40}}>
        <div>
          <div style={{fontFamily: 'Inter', fontSize: 19, fontWeight: 900,
                       letterSpacing: '.14em', color: '#3FD2A0'}}>MONO</div>
          <div style={{fontFamily: 'JetBrainsMono', fontSize: 34, marginTop: 6}}>
            skills/engineering/grill
          </div>
        </div>
        <div>
          <div style={{fontFamily: 'Inter', fontSize: 19, fontWeight: 900,
                       letterSpacing: '.14em', color: '#3FD2A0'}}>SERIF TITLE</div>
          <div style={{fontFamily: 'Fraunces', fontSize: 46, fontStyle: 'italic',
                       marginTop: 6}}>Teaching The Agent</div>
          <div style={{fontFamily: 'PlayfairDisplay', fontSize: 46,
                       fontStyle: 'italic', marginTop: 4}}>Teaching The Agent</div>
        </div>
      </div>
    </div>
  </AbsoluteFill>
);
