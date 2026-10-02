import { S } from '../shared/state.js';
import { drawSnapshotToCanvas } from '../shared/canvas.js';
import { updateGcpUI } from '../shared/gcp.js';
import { updateAoiUI } from '../shared/aoi.js';

export function startLivePreview() {
  const url = document.getElementById('rtspUrl').value.trim();
  const img = document.getElementById('livePreview');
  const empty = document.getElementById('frameEmpty4a');
  img.onload = () => { if (empty) empty.style.display = 'none'; };
  img.onerror = () => {
    img.src = '';
    img.style.display = 'none';
    S.livePreviewActive = false;
    if (empty) {
      empty.style.display = '';
      const h3 = empty.querySelector('h3');
      if (h3) h3.textContent = 'Could not connect — retrying…';
    }
    setTimeout(() => {
      if (!S.frameCaptured) startLivePreview();
    }, 3000);
  };
  img.src = '/api/stream/live?rtsp_url=' + encodeURIComponent(url);
  img.style.display = 'block';
  S.livePreviewActive = true;
}

export function stopLivePreview() {
  const img = document.getElementById('livePreview');
  img.src = '';
  img.style.display = 'none';
  S.livePreviewActive = false;
}

export async function captureFrame() {
  const url = document.getElementById('rtspUrl').value.trim();
  const btn = document.getElementById('captureBtn');
  btn.disabled = true;
  btn.innerHTML = '… Capturing';
  try {
    const res = await fetch('/api/stream/snapshot?rtsp_url=' + encodeURIComponent(url));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const blob = await res.blob();
    S.snapshotImg = new Image();
    S.snapshotImg.onload = () => {
      S.videoWidth  = S.snapshotImg.naturalWidth;
      S.videoHeight = S.snapshotImg.naturalHeight;
      S.videoLoaded = true;
      S.frameCaptured = true;
      stopLivePreview();
      document.getElementById('frameCanvas4a').style.display = '';
      document.getElementById('overlayCanvas4a').style.display = '';
      drawSnapshotToCanvas(document.getElementById('frameCanvas4a'), document.getElementById('frameContainer4a'));
      drawSnapshotToCanvas(document.getElementById('frameCanvas4c'), document.getElementById('frameContainer4c'));
      document.getElementById('captureSection').style.display = 'none';
      document.getElementById('gcpSection').style.display = 'flex';
    };
    S.snapshotImg.src = URL.createObjectURL(blob);
  } catch(e) {
    alert('Capture failed: ' + e.message);
    btn.disabled = false;
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M4 8a2 2 0 0 1 2-2h1l2-2h6l2 2h1a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/></svg> Capture frame';
  }
}

export function recaptureFrame() {
  S.videoLoaded = false; S.frameCaptured = false;
  S.gcps = []; S.aoiCorners = []; S.originGcpIndex = -1;

  document.getElementById('gcpSection').style.display = 'none';
  document.getElementById('captureSection').style.display = 'flex';
  const btn = document.getElementById('captureBtn');
  btn.disabled = false;
  btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M4 8a2 2 0 0 1 2-2h1l2-2h6l2 2h1a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/></svg> Capture frame';

  try {
    ['frameCanvas4a', 'frameCanvas4c', 'overlayCanvas4a'].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.style.display = 'none';
      try { el.getContext('2d').clearRect(0, 0, el.width, el.height); } catch(_) {}
    });
  } catch(_) {}

  updateGcpUI();
  updateAoiUI();
  stopLivePreview();
  setTimeout(startLivePreview, 300);
}
