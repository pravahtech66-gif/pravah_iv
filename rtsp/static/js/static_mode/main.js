import { S } from '../shared/state.js';
import { makeShowStep } from '../shared/wizard.js';
import { getPixelCoords, installFrameResizeObserver } from '../shared/canvas.js';
import { setOrigin, updateGcpUI, removeGcp, redrawGcpOverlay } from '../shared/gcp.js';
import { updateAoiUI, updateAoiReadout, redrawAoiOverlay } from '../shared/aoi.js';
import { toggleSensor, onProtocolChange, testSensor } from '../shared/sensor.js';
import { updateHaDisplay } from '../shared/config.js';

import { handleVideoUpload, showStaticFrameStep } from './upload.js';
import { captureFrame, recaptureFrame } from './preview.js';
import { startStream } from './results.js';

const showStep = makeShowStep(n => {
  if (n === '4a') {
    showStaticFrameStep();
  }
});

document.addEventListener('DOMContentLoaded', () => {
  installFrameResizeObserver('frameContainer4a', 'frameCanvas4a');
  installFrameResizeObserver('frameContainer4c', 'frameCanvas4c');
  ['waterZ', 'camX', 'camY', 'camZ'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', updateHaDisplay);
  });

  document.getElementById('overlayCanvas4a').addEventListener('click', e => {
    if (!S.videoLoaded) return;
    const coords = getPixelCoords(e, document.getElementById('overlayCanvas4a'));
    S.pendingGcp = coords; S.editingGcpIndex = -1;
    const form = document.getElementById('gcpForm');
    form.classList.add('active');
    document.getElementById('gcpFormTitle').textContent = 'Point #' + (S.gcps.length + 1);
    document.getElementById('gcpFormPixel').textContent = 'Pixel: (' + coords.pixelX.toFixed(1) + ', ' + coords.pixelY.toFixed(1) + ')';
    document.getElementById('gcpX').value = '';
    document.getElementById('gcpY').value = '';
    document.getElementById('gcpZ').value = '';
    document.getElementById('gcpX').focus();
    updateGcpUI(); redrawGcpOverlay();
  });

  document.getElementById('gcpSaveBtn').addEventListener('click', () => {
    const xIn = parseFloat(document.getElementById('gcpX').value);
    const yIn = parseFloat(document.getElementById('gcpY').value);
    const zIn = parseFloat(document.getElementById('gcpZ').value);
    if ([xIn, yIn, zIn].some(isNaN)) { alert('Enter valid numbers for X, Y, and Z.'); return; }
    const x = +(xIn * 0.0254).toFixed(6);
    const y = +(yIn * 0.0254).toFixed(6);
    const z = +(zIn * 0.0254).toFixed(6);
    if (S.editingGcpIndex >= 0) {
      S.gcps[S.editingGcpIndex] = { ...S.gcps[S.editingGcpIndex], x, y, z, xIn, yIn, zIn };
      S.editingGcpIndex = -1;
    } else {
      S.gcps.push({ ...S.pendingGcp, x, y, z, xIn, yIn, zIn });
    }
    S.pendingGcp = null;
    document.getElementById('gcpForm').classList.remove('active');
    updateGcpUI(); redrawGcpOverlay();
  });

  document.getElementById('gcpCancelBtn').addEventListener('click', () => {
    S.pendingGcp = null; S.editingGcpIndex = -1;
    document.getElementById('gcpForm').classList.remove('active');
    updateGcpUI(); redrawGcpOverlay();
  });

  document.getElementById('overlayCanvas4c').addEventListener('mousedown', e => {
    const coords = getPixelCoords(e, document.getElementById('overlayCanvas4c'));
    if (S.aoiCorners.length === 4) {
      for (let i = 0; i < 4; i++) {
        const dx = S.aoiCorners[i].dispX - coords.dispX;
        const dy = S.aoiCorners[i].dispY - coords.dispY;
        if (Math.sqrt(dx*dx + dy*dy) < 15) { S.draggingAoi = i; return; }
      }
      return;
    }
    S.aoiCorners.push(coords);
    updateAoiUI(); updateAoiReadout(); redrawAoiOverlay();
  });
  document.getElementById('overlayCanvas4c').addEventListener('mousemove', e => {
    if (S.draggingAoi < 0) return;
    S.aoiCorners[S.draggingAoi] = getPixelCoords(e, document.getElementById('overlayCanvas4c'));
    redrawAoiOverlay(); updateAoiReadout();
  });
  document.getElementById('overlayCanvas4c').addEventListener('mouseup', () => { S.draggingAoi = -1; });

  document.addEventListener('keydown', e => {
    if (S.currentStep !== '4c') return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && S.aoiCorners.length > 0) {
      S.aoiCorners.pop(); updateAoiUI(); updateAoiReadout(); redrawAoiOverlay();
    }
  });

  showStep(2);
});

window.showStep = showStep;
window.handleVideoUpload = handleVideoUpload;
window.captureFrame = captureFrame;
window.recaptureFrame = recaptureFrame;
window.updateHaDisplay = updateHaDisplay;
window.toggleSensor = toggleSensor;
window.onProtocolChange = onProtocolChange;
window.testSensor = testSensor;
window.startStream = startStream;
window.setOrigin = setOrigin;
window.removeGcp = removeGcp;
