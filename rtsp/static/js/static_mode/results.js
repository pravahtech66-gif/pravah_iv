import { S } from '../shared/state.js';
import { buildStreamConfig } from '../shared/config.js';
import { buildSensorConfig } from '../shared/sensor.js';
import { staticVideoFile } from './upload.js';

export const API = '';

const PIPELINE_NAME = 'quasi-v2 (Bodart 2024)';

export async function startStream() {
  if (!staticVideoFile) { alert('Please upload a video first.'); return; }
  const sensorEnabled = document.getElementById('sensorToggle').getAttribute('aria-checked') === 'true';
  const config = buildStreamConfig();
  if (sensorEnabled) {
    config.sensor_enabled = true;
    config.sensor_config = buildSensorConfig();
  }
  S.sessionConfig = config;

  window.showStep(6);
  setStaticStatus('Running ' + PIPELINE_NAME + '…');
  const container = document.getElementById('resultsContainer');
  if (container) container.innerHTML = '';

  createResultCard(0, PIPELINE_NAME);
  setCardStatus(0, 'running', 'Uploading & processing…');
  try {
    const fd = new FormData();
    fd.append('video', staticVideoFile, staticVideoFile.name);
    fd.append('config', JSON.stringify(config));

    const res = await fetch(`${API}/api/process`, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) { setCardStatus(0, 'error', 'Failed: ' + (data.error || res.status)); }
    else {
      const final = await pollJobUntilDone(0, data.job_id);
      if (final && final.status === 'done') renderCardResults(0, final);
      else setCardStatus(0, 'error', (final && final.error_message) || 'pipeline failed');
    }
  } catch (e) {
    setCardStatus(0, 'error', 'Network error: ' + e.message);
  }
  setStaticStatus('✓ Finished');
}

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

export function pollJobUntilDone(cardIndex, jobId) {
  return new Promise(resolve => {
    const tick = async () => {
      let data;
      try {
        const res = await fetch(`${API}/api/status/${jobId}`);
        data = await res.json();
      } catch { setTimeout(tick, 2000); return; }
      if (data.error && !data.status) { resolve({ status: 'error', error_message: data.error }); return; }
      const log = document.getElementById('cardLog-' + cardIndex);
      if (log && data.progress_log) { log.textContent = data.progress_log.join('\n'); log.scrollTop = log.scrollHeight; }
      if (data.status === 'done' || data.status === 'error') { resolve(data); return; }
      setCardStatus(cardIndex, 'running', 'Status: ' + (data.status || 'processing') + '…');
      setTimeout(tick, 2000);
    };
    tick();
  });
}

export function setStaticStatus(msg) {
  const el = document.getElementById('staticStatus');
  if (el) el.textContent = msg;
}

export function createResultCard(index, name) {
  const container = document.getElementById('resultsContainer');
  if (!container) return;
  const card = document.createElement('div');
  card.id = 'card-' + index;
  card.style.cssText = 'background:#fff;border:1px solid rgba(11,43,58,0.08);border-radius:14px;box-shadow:var(--shadow-xs);padding:18px 20px;display:flex;flex-direction:column;gap:14px';
  card.innerHTML =
    '<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap">'
    +   '<div style="font-weight:600;color:var(--ink-900)"><span style="color:var(--ink-400);font-family:var(--font-mono)">#' + (index + 1) + '</span> &nbsp;' + escapeHtml(name) + '</div>'
    +   '<div id="cardStatus-' + index + '" style="font-family:var(--font-mono);font-size:12px;color:var(--ink-500)">queued</div>'
    + '</div>'
    + '<div style="display:flex;gap:12px;flex-wrap:wrap">'
    +   metricBox('Mean (m/s)', 'cardMean-' + index)
    +   metricBox('Median (m/s)', 'cardMedian-' + index)
    +   metricBox('Max (m/s)', 'cardMax-' + index)
    + '</div>'
    + '<div style="display:flex;gap:12px;flex-wrap:wrap">'
    +   '<img id="cardImage-' + index + '" alt="PIV result" style="display:none;max-width:100%;border-radius:10px;border:1px solid rgba(11,43,58,0.08)">'
    +   '<img id="cardOverlay-' + index + '" alt="Camera overlay" style="display:none;max-width:100%;border-radius:10px;border:1px solid rgba(11,43,58,0.08)">'
    + '</div>'
    + '<details><summary style="cursor:pointer;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:var(--ink-500)">Processing log</summary>'
    +   '<pre id="cardLog-' + index + '" style="background:#0b2b3a;color:#cfe8ec;font-family:var(--font-mono);font-size:11px;line-height:1.5;padding:12px 14px;border-radius:10px;max-height:260px;overflow:auto;white-space:pre-wrap;margin:8px 0 0"></pre>'
    + '</details>';
  container.appendChild(card);
}

export function metricBox(label, valueId) {
  return '<div style="flex:1;min-width:120px;background:var(--sand-100,#f7f5f0);border-radius:10px;padding:10px 14px">'
    + '<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.1em;color:var(--ink-500);font-weight:700">' + label + '</div>'
    + '<div id="' + valueId + '" style="font-size:22px;font-weight:600;color:var(--ink-900);font-family:var(--font-mono)">&mdash;</div></div>';
}

export function setCardStatus(index, state, msg) {
  const el = document.getElementById('cardStatus-' + index);
  if (!el) return;
  const colors = { queued: 'var(--ink-500)', running: 'var(--aqua-600)', done: 'var(--ok-400,#3DB97B)', error: 'var(--err-400,#D0594E)' };
  el.style.color = colors[state] || 'var(--ink-500)';
  el.textContent = msg || state;
}

export function renderCardResults(index, data) {
  setCardStatus(index, 'done', '✓ done');
  const fmt = v => (v == null ? '—' : (typeof v === 'number' ? v.toFixed(3) : v));
  const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = fmt(v); };
  set('cardMean-' + index, data.mean_speed);
  set('cardMedian-' + index, data.median_speed);
  set('cardMax-' + index, data.max_speed);
  const img = document.getElementById('cardImage-' + index);
  if (img && data.result_image_url) { img.src = data.result_image_url; img.style.display = ''; }
  const ov = document.getElementById('cardOverlay-' + index);
  if (ov && data.camera_overlay_url) { ov.src = data.camera_overlay_url; ov.style.display = ''; }
}
