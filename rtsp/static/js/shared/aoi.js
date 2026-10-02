import { S } from './state.js';

export function updateAoiUI() {
  const n = S.aoiCorners.length;
  document.getElementById('aoiReadoutN').textContent = n;
  document.getElementById('aoiReadout').style.display = n > 0 ? '' : 'none';
  document.getElementById('aoiNext').disabled = n < 4;
  const instr = document.getElementById('aoiInstruction');
  if (n < 4) instr.textContent = 'Click 4 corners of the water surface area. Order: top-left, top-right, bottom-right, bottom-left. (' + n + '/4)';
  else instr.textContent = 'AOI set. Drag corners to adjust.';
}

export function updateAoiReadout() {
  document.getElementById('aoiReadoutN').textContent = S.aoiCorners.length;
}

export function redrawAoiOverlay() {
  const canvas = document.getElementById('overlayCanvas4c');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (S.aoiCorners.length === 0) return;
  const rect = canvas.getBoundingClientRect();
  const sx = canvas.width / rect.width;
  const sy = canvas.height / rect.height;
  const pts = S.aoiCorners.map(c => [c.dispX*sx, c.dispY*sy]);

  if (pts.length === 4) {
    ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < 4; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.closePath();
    const g = ctx.createLinearGradient(pts[0][0], pts[0][1], pts[2][0], pts[2][1]);
    g.addColorStop(0, 'rgba(63,181,178,0.12)'); g.addColorStop(1, 'rgba(63,181,178,0.28)');
    ctx.fillStyle = g; ctx.fill();
  }
  ctx.save(); ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
  if (pts.length === 4) ctx.closePath();
  ctx.setLineDash([14, 8]); ctx.lineDashOffset = -S.aoiDashOffset;
  ctx.strokeStyle = '#3FB5B2'; ctx.lineWidth = 3;
  ctx.shadowColor = 'rgba(63,181,178,0.7)'; ctx.shadowBlur = 12; ctx.stroke(); ctx.restore();

  pts.forEach((p, i) => {
    const glowR = 18;
    const grd = ctx.createRadialGradient(p[0],p[1],4, p[0],p[1],glowR);
    grd.addColorStop(0,'rgba(63,181,178,0.75)'); grd.addColorStop(1,'rgba(63,181,178,0)');
    ctx.fillStyle = grd; ctx.beginPath(); ctx.arc(p[0],p[1],glowR,0,Math.PI*2); ctx.fill();
    ctx.beginPath(); ctx.arc(p[0],p[1],9,0,Math.PI*2);
    ctx.fillStyle='#fff'; ctx.fill(); ctx.strokeStyle='#3FB5B2'; ctx.lineWidth=3; ctx.stroke();
    ctx.fillStyle='#1E8F8F'; ctx.font='bold 10px "JetBrains Mono",monospace';
    ctx.textAlign='center'; ctx.textBaseline='middle'; ctx.fillText(i+1,p[0],p[1]);
  });

}

(function animateAoi() {
  S.aoiDashOffset = (S.aoiDashOffset + 0.7) % 22;
  if (S.aoiCorners.length >= 2) redrawAoiOverlay();
  requestAnimationFrame(animateAoi);
})();
