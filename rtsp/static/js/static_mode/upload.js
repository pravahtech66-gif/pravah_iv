import { S } from '../shared/state.js';
import { drawSnapshotToCanvas } from '../shared/canvas.js';

export const API = '';

export let staticVideoFile = null;

export function handleVideoUpload(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  staticVideoFile = file;
  S.videoLoaded = false; S.frameCaptured = false;
  const chipWrap = document.getElementById('videoStatusWrap');
  const chip = document.getElementById('videoChip');
  const next = document.getElementById('step2Next');
  if (next) next.disabled = true;
  if (chipWrap && chip) { chip.textContent = '⏳ Reading first frame…'; chipWrap.style.display = ''; }

  const fd = new FormData();
  fd.append('video', file, file.name);
  fetch(`${API}/api/static/first_frame`, { method: 'POST', body: fd })
    .then(async res => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || ('HTTP ' + res.status));
      }
      return res.blob();
    })
    .then(blob => {
      S.snapshotImg = new Image();
      S.snapshotImg.onload = () => {
        S.videoWidth  = S.snapshotImg.naturalWidth;
        S.videoHeight = S.snapshotImg.naturalHeight;
        S.videoLoaded = true;
        S.frameCaptured = true;
        if (next) next.disabled = false;
        if (chipWrap && chip) chip.textContent = '✓ ' + file.name + ' · ' + S.videoWidth + '×' + S.videoHeight;
      };
      S.snapshotImg.src = URL.createObjectURL(blob);
    })
    .catch(err => {
      if (chipWrap && chip) chip.textContent = '✗ ' + err.message;
      alert('Could not read first frame from video: ' + err.message);
    });
}

export function showStaticFrameStep() {
  if (!S.snapshotImg || !S.videoLoaded) return;
  const empty = document.getElementById('frameEmpty4a');
  if (empty) empty.style.display = 'none';
  document.getElementById('frameCanvas4a').style.display = '';
  document.getElementById('overlayCanvas4a').style.display = '';
  drawSnapshotToCanvas(document.getElementById('frameCanvas4a'), document.getElementById('frameContainer4a'));
  drawSnapshotToCanvas(document.getElementById('frameCanvas4c'), document.getElementById('frameContainer4c'));
  const cap = document.getElementById('captureSection');
  const gcp = document.getElementById('gcpSection');
  if (cap) cap.style.display = 'none';
  if (gcp) gcp.style.display = 'flex';
}
