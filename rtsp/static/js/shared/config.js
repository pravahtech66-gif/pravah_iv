import { S } from './state.js';

export function _inToM(inches) { return +((parseFloat(inches) || 0) * 0.0254).toFixed(6); }

export function updateHaDisplay() {
  const waterZM = _inToM(document.getElementById('waterZ').value);
  const el = document.getElementById('haFallbackDisplay');
  if (el) el.textContent = 'Water surface elevation = ' + waterZM.toFixed(4) + ' m from origin';
}

export function buildStreamConfig() {
  const camXM = _inToM(document.getElementById('camX').value);
  const camYM = _inToM(document.getElementById('camY').value);
  const camZM = _inToM(document.getElementById('camZ').value);
  const waterZM = _inToM(document.getElementById('waterZ').value);
  const ox = S.originGcpIndex >= 0 ? S.gcps[S.originGcpIndex].x : 0;
  const oy = S.originGcpIndex >= 0 ? S.gcps[S.originGcpIndex].y : 0;
  const oz = S.originGcpIndex >= 0 ? S.gcps[S.originGcpIndex].z : 0;
  const cfg = {
    frame_width:  S.videoWidth  || 1920,
    frame_height: S.videoHeight || 1080,
    gcps: {
      src:   S.gcps.map(g => [+g.pixelX.toFixed(2), +g.pixelY.toFixed(2)]),
      dst:   S.gcps.map(g => [+(g.x - ox).toFixed(6), +(g.y - oy).toFixed(6), +(g.z - oz).toFixed(6)]),
      z_0:   waterZM,
      h_ref: waterZM,
    },
    lens_position: [camXM, camYM, camZM],
    h_a:           waterZM,
    aoi_corners:   S.aoiCorners.map(c => [+c.pixelX.toFixed(2), +c.pixelY.toFixed(2)]),
  };
  return cfg;
}
