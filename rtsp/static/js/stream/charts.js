import { S } from '../shared/state.js';

let chartViewStart = [0, 0, 0];
const CHART_WINDOW = 20;

export function panChart(dir)  { chartViewStart[0] = Math.max(0, chartViewStart[0] + dir * 5); redrawCharts(); }
export function panChart2(dir) { chartViewStart[1] = Math.max(0, chartViewStart[1] + dir * 5); redrawCharts(); }
export function panChart3(dir) { chartViewStart[2] = Math.max(0, chartViewStart[2] + dir * 5); redrawCharts(); }

export function updateCharts(results) {
  redrawCharts(results);
}

export function redrawCharts(results) {
  results = results || (S.lastStatus ? S.lastStatus.results : []);
  if (!results) return;
  drawLineChart('chartMean',   results, r => r.mean_speed,   '#3FB5B2', 0);
  drawLineChart('chartMedian', results, r => r.median_speed, '#2F7E93', 1);
  drawLineChart('chartMax',    results, r => r.max_speed,    '#D0594E', 2);
}

export function drawLineChart(canvasId, results, getter, color, panIdx) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.offsetWidth || 600;
  const H = 80;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const pad = { l: 40, r: 12, t: 8, b: 24 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;

  ctx.clearRect(0, 0, W, H);

  ctx.fillStyle = '#FAFAF8';
  ctx.fillRect(0, 0, W, H);

  const total = results.length;
  const off = Math.max(0, total - CHART_WINDOW - chartViewStart[panIdx]);
  const visible = results.slice(off, off + CHART_WINDOW);
  const data = visible.map(getter).filter(v => v != null);

  if (data.length < 1) {
    ctx.fillStyle = '#B4C3CA';
    ctx.font = '11px JetBrains Mono, monospace';
    ctx.textAlign = 'center';
    ctx.fillText('No data yet', W / 2, H / 2 + 4);
    return;
  }

  const minV = Math.min(...data) * 0.85;
  const maxV = Math.max(...data) * 1.15 || 1;
  const range = maxV - minV || 1;

  ctx.strokeStyle = '#E8E1D4';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 2; i++) {
    const y = pad.t + (plotH / 2) * i;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + plotW, y); ctx.stroke();
    const label = (maxV - (range / 2) * i).toFixed(2);
    ctx.fillStyle = '#7A93A0';
    ctx.font = '9px JetBrains Mono, monospace';
    ctx.textAlign = 'right';
    ctx.fillText(label, pad.l - 4, y + 3);
  }

  const toY = v => pad.t + plotH - ((v - minV) / range) * plotH;
  const toX = i => pad.l + (i / Math.max(visible.length - 1, 1)) * plotW;

  const pts = [];
  visible.forEach((r, i) => {
    const v = getter(r);
    if (v != null) pts.push({ x: toX(i), y: toY(v), label: 'B' + (r.batch + 1) });
  });
  if (!pts.length) return;

  ctx.beginPath();
  ctx.moveTo(pts[0].x, pad.t + plotH);
  pts.forEach(p => ctx.lineTo(p.x, p.y));
  ctx.lineTo(pts[pts.length - 1].x, pad.t + plotH);
  ctx.closePath();
  ctx.fillStyle = color + '18';
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  pts.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.lineJoin = 'round';
  ctx.stroke();

  pts.forEach((p, i) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 3, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();
    if (i % Math.max(1, Math.floor(pts.length / 8)) === 0 || i === pts.length - 1) {
      ctx.fillStyle = '#7A93A0';
      ctx.font = '9px JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(p.label, p.x, H - 6);
    }
  });
}

window.addEventListener('resize', () => { if (S.lastStatus) redrawCharts(); });
