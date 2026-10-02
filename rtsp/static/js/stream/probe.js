import { S } from '../shared/state.js';
import { loadCameraSettingsPanel, hideCameraSettingsPanel } from './camera_settings.js';

export const API = '';

export async function testRtsp() {
  const url = document.getElementById('rtspUrl').value.trim();
  if (!url) return;
  const badge = document.getElementById('probeBadge');
  badge.style.display = 'none';
  hideCameraSettingsPanel();
  const btn = document.getElementById('probeBtn');
  btn.disabled = true;
  btn.textContent = 'Testing…';
  try {
    const res = await fetch(`${API}/api/stream/probe?rtsp_url=` + encodeURIComponent(url));
    const data = await res.json();
    badge.style.display = 'inline-flex';
    badge.className = 'probe-badge ' + (data.ok ? 'ok' : 'err');
    if (data.ok) {
      badge.textContent = `✓ ${data.fps.toFixed(1)} fps · ${data.width}×${data.height}` + (data.codec ? ` · ${data.codec}` : '');
      document.getElementById('step2Next').disabled = false;
      document.getElementById('recordBatchBtn').style.display = '';
      loadCameraSettingsPanel();
    } else {
      badge.textContent = '✗ ' + (data.error || 'Failed');
    }
  } catch(e) {
    badge.style.display = 'inline-flex';
    badge.className = 'probe-badge err';
    badge.textContent = '✗ Network error';
  }
  btn.disabled = false;
  btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg> Test connection`;
}

document.getElementById('rtspUrl').addEventListener('keydown', e => {
  if (e.key === 'Enter') testRtsp();
});

let _step2RecTimer = null;

export async function step2StartRecording() {
  const rtspUrl = document.getElementById('rtspUrl').value.trim();
  if (!rtspUrl) { alert('Enter an RTSP URL first.'); return; }
  const startBtn = document.getElementById('step2RecStartBtn');
  startBtn.disabled = true;
  try {
    const res = await fetch(`${API}/api/stream/record/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rtsp_url: rtspUrl }),
    });
    const d = await res.json();
    if (d.ok) {
      document.getElementById('step2RecStartBtn').style.display = 'none';
      document.getElementById('step2RecStopBtn').style.display  = 'inline-flex';
      const ind = document.getElementById('step2RecIndicator');
      const start = Date.now();
      _step2RecTimer = setInterval(() => {
        const elapsed = Math.floor((Date.now() - start) / 1000);
        const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
        const ss = String(elapsed % 60).padStart(2, '0');
        ind.textContent = `⏺ Recording ${mm}:${ss}`;
      }, 1000);
    } else {
      alert('Recording failed: ' + (d.error || 'unknown'));
      startBtn.disabled = false;
    }
  } catch (e) {
    alert('Network error: ' + e);
    startBtn.disabled = false;
  }
}

export async function step2StopRecording() {
  const stopBtn = document.getElementById('step2RecStopBtn');
  stopBtn.disabled = true;
  clearInterval(_step2RecTimer);
  try {
    const res = await fetch(`${API}/api/stream/record/stop`, { method: 'POST' });
    const d   = await res.json();
    const ind = document.getElementById('step2RecIndicator');
    if (d.ok && d.file) {
      ind.textContent = `Saved: ${d.file}`;
      setTimeout(() => { ind.textContent = ''; }, 8000);
    }
  } catch (e) {   }
  document.getElementById('step2RecStartBtn').style.display = 'inline-flex';
  document.getElementById('step2RecStartBtn').disabled = false;
  stopBtn.style.display = 'none';
  stopBtn.disabled = false;
}

let snapshotPollTimer = null;

export async function recordBatch() {
  const rtspUrl = document.getElementById('rtspUrl').value.trim();
  if (!rtspUrl) return;

  const btn  = document.getElementById('recordBatchBtn');
  const wrap = document.getElementById('snapshotStatusWrap');
  const chip = document.getElementById('snapshotChip');

  btn.disabled = true;
  btn.textContent = 'Recording…';
  wrap.style.display = '';
  chip.className = 'save-chip recording';
  chip.innerHTML = '⏺ Starting batch recording…';

  try {
    const res = await fetch('/api/stream/record_snapshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rtsp_url: rtspUrl, duration_s: S.selectedDurationS }),
    });
    const data = await res.json();
    if (!res.ok) {
      chip.className = 'save-chip failed';
      chip.innerHTML = '✗ Could not start recording: ' + (data.error || res.status);
      btn.disabled = false;
      btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4" fill="currentColor"/></svg> Record batch';
      return;
    }
  } catch(e) {
    chip.className = 'save-chip failed';
    chip.innerHTML = '✗ Network error: ' + e.message;
    btn.disabled = false;
    btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4" fill="currentColor"/></svg> Record batch';
    return;
  }

  if (snapshotPollTimer) clearInterval(snapshotPollTimer);
  snapshotPollTimer = setInterval(pollSnapshotStatus, 3000);
}

export async function pollSnapshotStatus() {
  let data;
  try {
    const res = await fetch('/api/stream/snapshot_status');
    data = await res.json();
  } catch { return; }

  const chip = document.getElementById('snapshotChip');
  if (!chip) return;

  const total   = data.total_clips || 3;
  const idx     = data.clip_index || 0;
  const nSaved  = (data.saved_paths || []).length;
  const progress = total ? ' (' + Math.max(idx, 1) + '/' + total + ')' : '';

  const folder = data.folder || '';
  const folderLabel = folder ? ' → ' + folder + '/' : '';
  const btn = document.getElementById('recordBatchBtn');
  const attempt = data.attempt || 1;
  const attemptLabel = attempt > 1 ? ' (attempt ' + attempt + ')' : '';
  const recBtnSvg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4" fill="currentColor"/></svg> ';

  switch (data.status) {
    case 'recording':
      chip.className = 'save-chip recording';
      chip.innerHTML = '⏺ Recording clip ' + Math.max(idx, 1) + '/' + total + attemptLabel + folderLabel;
      break;
    case 'rejected':
      chip.className = 'save-chip failed';
      chip.textContent = '⚠ ' + (data.error || 'Clip ' + Math.max(idx, 1) + ' rejected (disruption)' + attemptLabel) + ' — retrying';
      break;
    case 'saving':
      chip.className = 'save-chip saving';
      chip.innerHTML = '<span class="spin">⟳</span> Saving clip ' + idx + '/' + total + folderLabel;
      break;
    case 'saved': {
      chip.className = 'save-chip saved';
      chip.innerHTML = '✓ Saved ' + nSaved + '/' + total + ' clips' + folderLabel;
      clearInterval(snapshotPollTimer);
      snapshotPollTimer = null;
      btn.disabled = false;
      btn.innerHTML = recBtnSvg + 'Record batch';
      break;
    }
    case 'failed':
      chip.className = 'save-chip failed';
      chip.innerHTML = '✗ Save failed' +
        (nSaved ? ' (' + nSaved + '/' + total + ' saved)' : '') +
        (data.error ? ': ' + data.error : '');
      clearInterval(snapshotPollTimer);
      snapshotPollTimer = null;
      btn.disabled = false;
      btn.innerHTML = recBtnSvg + 'Record batch';
      break;
  }
}
