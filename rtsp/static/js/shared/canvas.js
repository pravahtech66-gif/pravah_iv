import { S } from './state.js';
import { redrawGcpOverlay } from './gcp.js';
import { redrawAoiOverlay, updateAoiReadout } from './aoi.js';

export function drawSnapshotToCanvas(canvas, container) {
  if (!S.snapshotImg || !canvas || !container) return;
  canvas.width  = S.videoWidth;
  canvas.height = S.videoHeight;
  canvas.getContext('2d').drawImage(S.snapshotImg, 0, 0, S.videoWidth, S.videoHeight);
  requestAnimationFrame(() => sizeCanvasToContainer(canvas, container));
}

export function sizeCanvasToContainer(canvas, container) {
  if (!S.videoWidth || !S.videoHeight) return;
  const INSET = 18;
  const availW = Math.max(0, container.clientWidth  - 2 * INSET);
  const availH = Math.max(0, container.clientHeight - 2 * INSET);
  if (availW <= 0 || availH <= 0) return;
  const scale = Math.min(availW / S.videoWidth, availH / S.videoHeight);
  canvas.style.width  = Math.max(1, Math.round(S.videoWidth  * scale)) + 'px';
  canvas.style.height = Math.max(1, Math.round(S.videoHeight * scale)) + 'px';
  fitOverlay(canvas, container);
}

export function fitOverlay(frameCanvas, container) {
  const overlay = container.querySelector('.overlay-canvas');
  if (!overlay) return;
  requestAnimationFrame(() => {
    const rect     = frameCanvas.getBoundingClientRect();
    const contRect = container.getBoundingClientRect();
    overlay.width  = S.videoWidth;
    overlay.height = S.videoHeight;
    overlay.style.width  = rect.width  + 'px';
    overlay.style.height = rect.height + 'px';
    overlay.style.left   = (rect.left - contRect.left) + 'px';
    overlay.style.top    = (rect.top  - contRect.top)  + 'px';
  });
}

export function getPixelCoords(e, canvas) {
  const rect = canvas.getBoundingClientRect();
  const dispX = e.clientX - rect.left;
  const dispY = e.clientY - rect.top;
  const pixelX = dispX * (canvas.width  / rect.width);
  const pixelY = dispY * (canvas.height / rect.height);
  return { dispX, dispY, pixelX, pixelY };
}

export function installFrameResizeObserver(containerId, canvasId) {
  const container = document.getElementById(containerId);
  const canvas    = document.getElementById(canvasId);
  if (!container || !canvas || typeof ResizeObserver === 'undefined') return;
  let scheduled = false;
  new ResizeObserver(() => {
    if (scheduled) return; scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      if (!S.videoLoaded) return;
      sizeCanvasToContainer(canvas, container);
      if (containerId === 'frameContainer4a') redrawGcpOverlay();
      if (containerId === 'frameContainer4c') { redrawAoiOverlay(); updateAoiReadout(); }
    });
  }).observe(container);
}

export function drawMarker(ctx, x, y, num, label, pending, color, isOrigin) {
  color = color || '#3FB5B2';
  const grd = ctx.createRadialGradient(x, y, 4, x, y, 22);
  grd.addColorStop(0, color + 'AA'); grd.addColorStop(1, color + '00');
  ctx.fillStyle = grd; ctx.beginPath(); ctx.arc(x, y, 22, 0, Math.PI*2); ctx.fill();
  if (isOrigin) {
    ctx.beginPath(); ctx.arc(x, y, 16, 0, Math.PI*2);
    ctx.strokeStyle = '#f5c518'; ctx.lineWidth = 2.5; ctx.globalAlpha = 0.9; ctx.stroke(); ctx.globalAlpha = 1;
  }
  ctx.beginPath(); ctx.arc(x, y, 12, 0, Math.PI*2);
  ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.globalAlpha = pending ? 0.4 : 0.7; ctx.stroke(); ctx.globalAlpha = 1;
  ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI*2);
  ctx.fillStyle = pending ? color+'99' : color; ctx.fill();
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 2.5; ctx.stroke();
  ctx.fillStyle = '#fff'; ctx.font = 'bold 11px "JetBrains Mono",monospace';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(num, x, y);
  if (label) {
    const displayLabel = isOrigin ? '★ ' + label : label;
    ctx.font = '11px "JetBrains Mono",monospace';
    const tw = ctx.measureText(displayLabel).width;
    ctx.fillStyle = 'rgba(10,30,43,0.85)'; roundRect(ctx, x+14, y-10, tw+10, 20, 4); ctx.fill();
    ctx.fillStyle = isOrigin ? '#f5c518' : '#E8F3F6'; ctx.textAlign = 'left'; ctx.fillText(displayLabel, x+19, y);
  }
}

export function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath(); ctx.moveTo(x+r, y);
  ctx.arcTo(x+w,y, x+w,y+h, r); ctx.arcTo(x+w,y+h, x,y+h, r);
  ctx.arcTo(x,y+h, x,y, r);     ctx.arcTo(x,y, x+w,y, r);
  ctx.closePath();
}
