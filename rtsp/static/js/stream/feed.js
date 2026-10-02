import { S } from '../shared/state.js';

export function drawFeedCanvas(data) {
  const canvas = document.getElementById('feedCanvas');
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.offsetWidth || 800;
  const H = 280;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  ctx.fillStyle = '#0A1E2B';
  ctx.fillRect(0, 0, W, H);

  ctx.strokeStyle = 'rgba(255,255,255,0.04)';
  ctx.lineWidth = 1;
  for (let x = 0; x < W; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
  for (let y = 0; y < H; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }

  const cfg = S.sessionConfig;
  const fw = cfg.frame_width || 1920;
  const fh = cfg.frame_height || 1080;
  const sx = W / fw;
  const sy = H / fh;

  const aoi = cfg.aoi_corners;
  if (aoi && aoi.length === 4) {
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = '#E0A94D';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(aoi[0][0] * sx, aoi[0][1] * sy);
    for (let i = 1; i < 4; i++) ctx.lineTo(aoi[i][0] * sx, aoi[i][1] * sy);
    ctx.closePath();
    ctx.stroke();
    ctx.setLineDash([]);
  }

  const gcpSrc = cfg.gcps && cfg.gcps.src;
  if (gcpSrc) {
    gcpSrc.forEach(([px, py], i) => {
      ctx.beginPath();
      ctx.arc(px * sx, py * sy, 5, 0, 2 * Math.PI);
      ctx.fillStyle = '#3DB97B';
      ctx.fill();
      ctx.fillStyle = 'rgba(255,255,255,0.7)';
      ctx.font = 'bold 9px JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(i + 1, px * sx, py * sy + 14);
    });
  }

  const lastVelocityGrid = data && data.last_velocity_grid;
  if (lastVelocityGrid) {
  } else {
    ctx.fillStyle = 'rgba(255,255,255,0.25)';
    ctx.font = '12px Space Grotesk, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No vector data yet', W / 2, H / 2);
    ctx.font = '10px JetBrains Mono, monospace';
    ctx.fillStyle = 'rgba(255,255,255,0.12)';
    ctx.fillText('vectors will appear when last_velocity_grid is populated', W / 2, H / 2 + 20);
  }

  if (data && data.results && data.results.length > 0) {
    const last = data.results[data.results.length - 1];
    document.getElementById('feedBatchNum').textContent = last.batch + 1;
  }
}
