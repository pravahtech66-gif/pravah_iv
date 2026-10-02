import { S } from './state.js';
import { drawMarker } from './canvas.js';

export const GCP_COLORS = ['#3FB5B2','#E0A94D','#6FD0CC','#3DB97B','#2F7E93','#D0594E','#8EC4D0','#1E8F8F'];

export function setOrigin(i) {
  S.originGcpIndex = (S.originGcpIndex === i) ? -1 : i;
  updateGcpUI();
  redrawGcpOverlay();
}

export function updateGcpUI() {
  document.getElementById('gcpCounter').textContent = S.gcps.length + ' of 4 minimum points placed';
  document.getElementById('gcpNext').disabled = S.gcps.length < 4;
  const list = document.getElementById('gcpList');
  list.innerHTML = '';
  S.gcps.forEach((g, i) => {
    const isOrigin = (i === S.originGcpIndex);
    const item = document.createElement('div');
    item.className = 'gcp-item';
    item.innerHTML = `
      <div class="info">
        <span class="num">${i+1}</span>
        ${isOrigin ? '<span style="color:#f5c518;font-weight:700;font-size:11px;margin-right:4px;">★ origin</span>' : ''}
        (${g.xIn}, ${g.yIn}, ${g.zIn}) in
      </div>
      <div style="display:flex;gap:4px;align-items:center">
        <button class="btn btn-sm btn-ghost" style="font-size:10px;padding:2px 6px;" onclick="setOrigin(${i})">${isOrigin ? 'Clear origin' : '⊕ Origin'}</button>
        <button class="rm-btn" onclick="removeGcp(${i})">×</button>
      </div>`;
    item.querySelector('.info').addEventListener('click', () => {
      S.editingGcpIndex = i;
      document.getElementById('gcpFormTitle').textContent = 'Edit Point #' + (i+1);
      document.getElementById('gcpFormPixel').textContent = 'Pixel: (' + g.pixelX.toFixed(1) + ', ' + g.pixelY.toFixed(1) + ')';
      document.getElementById('gcpX').value = g.xIn;
      document.getElementById('gcpY').value = g.yIn;
      document.getElementById('gcpZ').value = g.zIn;
      document.getElementById('gcpForm').classList.add('active');
      document.getElementById('gcpX').focus();
    });
    list.appendChild(item);
  });
}

export function removeGcp(i) { S.gcps.splice(i, 1); updateGcpUI(); redrawGcpOverlay(); }

export function redrawGcpOverlay() {
  const canvas = document.getElementById('overlayCanvas4a');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const rect = canvas.getBoundingClientRect();
  const sx = canvas.width / rect.width;
  const sy = canvas.height / rect.height;
  S.gcps.forEach((g, i) => drawMarker(ctx, g.dispX*sx, g.dispY*sy, i+1, `(${g.xIn}, ${g.yIn}, ${g.zIn}) in`, false, GCP_COLORS[i % GCP_COLORS.length], i === S.originGcpIndex));
  if (S.pendingGcp) drawMarker(ctx, S.pendingGcp.dispX*sx, S.pendingGcp.dispY*sy, S.gcps.length+1, null, true, GCP_COLORS[S.gcps.length % GCP_COLORS.length]);
}
