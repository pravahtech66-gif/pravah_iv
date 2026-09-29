import { S } from '../shared/state.js';
import { updateCharts } from './charts.js';
import { drawFeedCanvas } from './feed.js';

export const API = '';

export async function patchDuration() {
  const newDur = parseInt(document.getElementById('dashDuration').value);
  try {
    await fetch(`${API}/api/stream/config`, {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ batch_duration_s: newDur })
    });
  } catch {}
}

export function startPolling() {
  if (S.pollTimer) clearInterval(S.pollTimer);
  if (S.tickTimer) clearInterval(S.tickTimer);
  S.pollTimer = setInterval(pollStatus, 2000);
  S.tickTimer = setInterval(tickProgress, 1000);
}

export async function pollStatus() {
  let data;
  try {
    const res = await fetch(`${API}/api/stream/status`);
    data = await res.json();
  } catch { return; }

  S.lastStatus = data;
  if (data.recording_started_at) S.recordingStartedAt = data.recording_started_at * 1000;

  updateBadges(data);
  updateRecordingUI(data);
  updateProgressRow(data);
  updateMetricCards(data.results || []);
  updateCharts(data.results || []);
  drawFeedCanvas(data);
  updateSaveStatus(data);

  if (data.warn_batch_dropped) showWarn('Processor busy — batch dropped. New batch recording.');
  if (data.warn_duration_changed) showWarn('Batch duration changed — current batch dropped and restarted.');

  if (data.status === 'stopped' || data.status === 'error') {
    clearInterval(S.pollTimer);
    clearInterval(S.tickTimer);
    showSessionEndOverlay(data);
  }
}

export function updateRecordingUI(data) {
  const recStartBtn  = document.getElementById('recStartBtn');
  const recStopBtn   = document.getElementById('recStopBtn');
  const recIndicator = document.getElementById('recIndicator');
  if (!recStartBtn) return;

  const isRunning = data.status === 'running';
  const isRec     = !!data.is_recording;

  recStartBtn.style.display = isRunning && !isRec ? 'inline-flex' : 'none';
  recStopBtn.style.display  = isRec ? 'inline-flex' : 'none';

  if (isRec && data.rec_started_at) {
    const elapsed = Math.floor(Date.now() / 1000 - data.rec_started_at);
    const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
    const ss = String(elapsed % 60).padStart(2, '0');
    recIndicator.textContent = `⏺ Recording ${mm}:${ss}`;
    recIndicator.style.display = 'inline';
  } else if (!isRec && recIndicator.textContent && !recIndicator.textContent.startsWith('Saved')) {
    recIndicator.style.display = 'none';
  }
}

export async function startRecording() {
  const recStartBtn = document.getElementById('recStartBtn');
  recStartBtn.disabled = true;
  try {
    const res = await fetch(`${API}/api/stream/record/start`, { method: 'POST' });
    const d   = await res.json();
    if (!d.ok) alert('Recording failed: ' + (d.error || 'unknown error'));
  } catch (e) {
    alert('Network error starting recording: ' + e);
  } finally {
    recStartBtn.disabled = false;
  }
}

export async function stopRecording() {
  const recStopBtn   = document.getElementById('recStopBtn');
  const recIndicator = document.getElementById('recIndicator');
  recStopBtn.disabled = true;
  try {
    const res = await fetch(`${API}/api/stream/record/stop`, { method: 'POST' });
    const d   = await res.json();
    if (d.ok && d.file) {
      recIndicator.textContent  = `Saved: ${d.file}`;
      recIndicator.style.display = 'inline';
      setTimeout(() => { recIndicator.style.display = 'none'; recIndicator.textContent = ''; }, 8000);
    } else if (!d.ok) {
      alert('Stop recording failed: ' + (d.error || 'unknown error'));
    }
  } catch (e) {
    alert('Network error stopping recording: ' + e);
  } finally {
    recStopBtn.disabled = false;
  }
}

export function updateBadges(data) {
  const recBadge  = document.getElementById('recBadge');
  const procBadge = document.getElementById('procBadge');
  const recNum = data.batch_index_recording ?? '—';

  if (data.status === 'running' && data.cooldown_until) {
    const remaining = Math.max(0, Math.ceil(data.cooldown_until - Date.now()/1000));
    const mm = String(Math.floor(remaining/60)).padStart(2,'0');
    const ss = String(remaining%60).padStart(2,'0');
    recBadge.className = 'status-badge idle';
    recBadge.innerHTML = `<span class="dot"></span>⏸ Next recording in ${mm}:${ss}`;
  } else if (data.status === 'running') {
    recBadge.className = 'status-badge recording';
    recBadge.innerHTML = `<span class="dot"></span>● Recording batch ${recNum}`;
  } else {
    recBadge.className = 'status-badge idle';
    recBadge.innerHTML = `<span class="dot"></span>${data.status}`;
  }

  const procIdx = data.batch_index_processing;
  if (procIdx !== null && procIdx !== undefined) {
    procBadge.className = 'status-badge processing';
    procBadge.innerHTML = `<span class="dot"></span>⟳ Processing batch ${procIdx}`;
    document.getElementById('procAnim').style.display = '';
    document.getElementById('procLabel').textContent = `Processing batch ${procIdx}`;
  } else {
    procBadge.className = 'status-badge idle';
    procBadge.innerHTML = `<span class="dot"></span>✓ Processor idle`;
    document.getElementById('procAnim').style.display = 'none';
    document.getElementById('procLabel').textContent = 'Processor idle';
  }
  document.getElementById('recBatchNum').textContent = recNum;
}

export function updateProgressRow(data) {
  const results = data.results || [];
  if (results.length > 0) {
    const last = results[results.length - 1];
    const mean = last.mean_speed != null ? last.mean_speed.toFixed(3) + ' m/s mean' : '—';
    document.getElementById('lastResultPill').textContent = `Last: batch ${last.batch} — ${mean}`;
    renderFitnessBadge(last);
  }
}

export function renderFitnessBadge(result) {
  const badge = document.getElementById('lastFitnessBadge');
  const score = result.fitness_score != null ? result.fitness_score.toFixed(1) + '/10' : '';
  badge.title = (result.fitness_reasons || []).join('; ');
  switch (result.fitness_status) {
    case 'ok':
      badge.className = 'fitness-badge ok';
      badge.textContent = 'Fit ' + score;
      break;
    case 'low_confidence':
      badge.className = 'fitness-badge low';
      badge.textContent = 'Low confidence ' + score;
      break;
    case 'invalid':
      badge.className = 'fitness-badge invalid';
      badge.textContent = 'Invalid — camera moved, recalibrate';
      break;
    default:
      badge.style.display = 'none';
      return;
  }
  badge.style.display = '';
}

export function tickProgress() {
  if (!S.recordingStartedAt || !S.lastStatus) return;
  const durationMs = (S.lastStatus.batch_duration_s || 60) * 1000;
  const elapsed = Date.now() - S.recordingStartedAt;
  const pct = Math.min(100, (elapsed / durationMs) * 100);
  document.getElementById('recProgress').style.width = pct + '%';

  const elSec = Math.floor(elapsed / 1000);
  const totSec = S.lastStatus.batch_duration_s || 60;
  const fmt = s => String(Math.floor(s / 60)).padStart(1,'0') + ':' + String(s % 60).padStart(2,'0');
  document.getElementById('recTimeLabel').textContent = fmt(elSec) + ' / ' + fmt(totSec);
}

export function updateMetricCards(results) {
  if (!results.length) return;
  const last = results[results.length - 1];
  const prev = results.length > 1 ? results[results.length - 2] : null;

  setMetric('mMean',   'dMean',   last.mean_speed,   prev?.mean_speed);
  setMetric('mMedian', 'dMedian', last.median_speed, prev?.median_speed);
  setMetric('mMax',    'dMax',    last.max_speed,     prev?.max_speed);
}

export function setMetric(valId, deltaId, val, prevVal) {
  const el = document.getElementById(valId);
  const del = document.getElementById(deltaId);
  if (val == null) { el.textContent = '—'; del.textContent = '—'; del.className = 'm-delta flat'; return; }
  el.textContent = val.toFixed(3);
  if (prevVal != null) {
    const diff = val - prevVal;
    const sign = diff > 0 ? '+' : '';
    del.textContent = sign + diff.toFixed(3) + ' m/s';
    del.className = 'm-delta ' + (diff > 0.001 ? 'up' : diff < -0.001 ? 'down' : 'flat');
  } else {
    del.textContent = '—'; del.className = 'm-delta flat';
  }
}

export async function saveExtraBatch() {
  const btn = document.getElementById('saveExtraBtn');
  btn.disabled = true;
  try {
    const res = await fetch('/api/stream/save_batch', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) {
      alert('Could not queue save: ' + (data.error || res.status));
      btn.disabled = false;
    }
  } catch(e) {
    alert('Network error: ' + e.message);
    btn.disabled = false;
  }
}

export function updateSaveStatus(data) {
  const bar     = document.getElementById('saveStatusBar');
  const exChip  = document.getElementById('extraSaveChip');
  const saveBtn = document.getElementById('saveExtraBtn');

  const exst   = data.extra_save_status;
  const exidx  = data.extra_save_batch_idx;
  const queued = data.save_next_queued;

  function renderChip(el, status, label) {
    if (!status && !label) { el.style.display = 'none'; return; }
    el.style.display = 'inline-flex';
    let cls, icon;
    switch (status) {
      case 'recording': cls = 'recording'; icon = '⏺'; break;
      case 'saving':    cls = 'saving';    icon = '<span class="spin">⟳</span>'; break;
      case 'saved':     cls = 'saved';     icon = '✓'; break;
      case 'failed':    cls = 'failed';    icon = '✗'; break;
      default:          cls = 'queued';    icon = '…'; break;
    }
    el.className = 'save-chip ' + cls;
    el.innerHTML = icon + ' ' + label;
  }

  let barVisible = false;

  if (queued && !exst) {
    barVisible = true;
    renderChip(exChip, 'queued', 'Next batch queued for Desktop save');
  } else if (exst) {
    barVisible = true;
    const fname  = data.extra_save_path ? data.extra_save_path.split(/[\\/]/).pop() : '';
    const bLabel = exidx != null ? ' batch ' + exidx : '';
    const label  =
      exst === 'recording' ? 'Recording' + bLabel + ' for Desktop save' :
      exst === 'saving'    ? 'Saving' + bLabel + ' to Desktop…' :
      exst === 'saved'     ? 'Batch' + bLabel + ' saved — ' + fname :
                             'Batch' + bLabel + ' save failed';
    renderChip(exChip, exst, label);
  } else {
    exChip.style.display = 'none';
  }

  if (data.status === 'running') {
    saveBtn.style.display = '';
    const busy = queued || exst === 'recording' || exst === 'saving';
    saveBtn.disabled = busy;
    saveBtn.textContent = busy ? '… Saving' : '+ Save extra batch';
    barVisible = true;
  } else {
    saveBtn.style.display = 'none';
  }

  bar.style.display = barVisible ? 'flex' : 'none';
}

let warnTimer = null;
export function showWarn(msg) {
  const banner = document.getElementById('warnBanner');
  document.getElementById('warnText').textContent = msg;
  banner.style.display = 'flex';
  clearTimeout(warnTimer);
  warnTimer = setTimeout(() => { banner.style.display = 'none'; }, 6000);
}
export function dismissWarn() {
  document.getElementById('warnBanner').style.display = 'none';
}

export function showSessionEndOverlay(data) {
  const results = data.results || [];
  const nBatches = results.length;
  const means = results.map(r => r.mean_speed).filter(v => v != null);
  const avgMean = means.length ? (means.reduce((a,b)=>a+b,0)/means.length).toFixed(3) : '—';

  const overlay = document.createElement('div');
  overlay.className = 'session-overlay';
  overlay.innerHTML = `
    <div class="session-overlay-card">
      <h2>${data.status === 'error' ? 'Session error' : 'Session ended'}</h2>
      ${data.status === 'error' && data.log && data.log.length ? `<p style="font-family:var(--font-mono);font-size:11px;color:var(--err-400);background:var(--err-100);padding:8px 12px;border-radius:8px;text-align:left">${data.log[data.log.length-1]}</p>` : ''}
      <div class="session-stat-row">
        <div class="session-stat"><div class="sv">${nBatches}</div><div class="sk">Batches processed</div></div>
        <div class="session-stat"><div class="sv">${avgMean}</div><div class="sk">Mean of means (m/s)</div></div>
      </div>
      <button class="btn btn-primary" onclick="location.reload()">Start new session</button>
    </div>`;
  document.body.appendChild(overlay);
}
