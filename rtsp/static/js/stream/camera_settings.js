let cameraSettingsActionResult = '';

const CAMERA_APPLY_FIELDS = [
  ['fps',              'Frame rate',               v => v + ' fps'],
  ['gop',              'Keyframe interval (GOP)',  v => v + ' frames'],
  ['bitrate_kbps',     'Bitrate',                  v => v + ' kbps'],
  ['constant_bitrate', 'Constant bitrate',         v => v ? 'on' : 'off'],
];

function escapeCameraText(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function formatCameraClockOffset(s) {
  return (s > 0 ? '+' : '') + s + ' s';
}

function readCameraRtspUrl() {
  return document.getElementById('rtspUrl').value.trim();
}

export function hideCameraSettingsPanel() {
  cameraSettingsActionResult = '';
  document.getElementById('cameraSettingsPanel').style.display = 'none';
}

export async function loadCameraSettingsPanel() {
  const panel = document.getElementById('cameraSettingsPanel');
  panel.style.display = '';
  panel.innerHTML = '<p class="camera-settings-muted">Reading camera settings…</p>';
  let data;
  try {
    const res = await fetch('/api/camera/settings?rtsp_url=' + encodeURIComponent(readCameraRtspUrl()));
    data = await res.json();
  } catch (e) {
    data = { ok: false, error: e.message };
  }
  if (!data.ok) {
    panel.innerHTML = '<p class="camera-settings-muted">Camera settings unavailable' +
      (data.error ? ' (' + escapeCameraText(data.error) + ')' : '') + '</p>' +
      (cameraSettingsActionResult ? `<p class="camera-settings-result">${escapeCameraText(cameraSettingsActionResult)}</p>` : '');
    return;
  }
  renderCameraSettingsPanel(data);
}

function renderCameraSettingsPanel(data) {
  const s = data.settings, r = data.recommended;
  const show = v => v == null ? '—' : escapeCameraText(v);
  const rows = [
    ['Codec',            show(s.encoding),                        show(r.encoding)],
    ['Resolution',       show(s.width) + '×' + show(s.height),    show(r.width) + '×' + show(r.height)],
    ['Frame rate',       show(s.fps) + ' fps',                    show(r.fps) + ' fps'],
    ['GOP',              show(s.gop) + ' frames',                 show(r.gop) + ' frames'],
    ['Bitrate',          show(s.bitrate_kbps) + ' kbps',          show(r.bitrate_kbps) + ' kbps'],
    ['Constant bitrate', s.constant_bitrate == null ? '—' : (s.constant_bitrate ? 'on' : 'off'),
                         r.constant_bitrate ? 'on' : 'off'],
    ['Camera clock',     formatCameraClockOffset(s.camera_clock_offset_s), 'laptop time'],
  ];
  const mismatches = data.mismatches || [];

  const panel = document.getElementById('cameraSettingsPanel');
  panel.innerHTML = `
    <div class="camera-settings-title">Camera settings</div>
    <table class="camera-settings-table">
      <tr><th></th><th>Current</th><th>Recommended</th></tr>
      ${rows.map(([k, cur, rec]) => `<tr><td>${k}</td><td>${cur}</td><td>${rec}</td></tr>`).join('')}
    </table>
    ${mismatches.length
      ? `<ul class="camera-settings-warn">${mismatches.map(m => `<li>⚠ ${escapeCameraText(m)}</li>`).join('')}</ul>`
      : '<p class="camera-settings-ok">✓ Matches recommended settings</p>'}
    ${cameraSettingsActionResult ? `<p class="camera-settings-result">${escapeCameraText(cameraSettingsActionResult)}</p>` : ''}
    <div class="camera-settings-actions">
      <button class="btn btn-aqua btn-sm" id="cameraApplyBtn">Apply recommended settings</button>
      <button class="btn btn-aqua btn-sm" id="cameraClockSyncBtn">Sync camera clock</button>
    </div>`;
  document.getElementById('cameraApplyBtn').addEventListener('click', () => applyRecommendedCameraSettings(data));
  document.getElementById('cameraClockSyncBtn').addEventListener('click', () => syncCameraClock(data));
}

async function postCameraWrite(path) {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rtsp_url: readCameraRtspUrl(), confirm: true }),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, error: 'Network error: ' + e.message };
  }
}

async function applyRecommendedCameraSettings(data) {
  const s = data.settings, r = data.recommended;
  const changes = CAMERA_APPLY_FIELDS
    .filter(([key]) => s[key] !== r[key])
    .map(([key, label, fmt]) => `• ${label}: ${s[key] == null ? 'unknown' : fmt(s[key])} → ${fmt(r[key])}`);
  const note = 'Resolution and codec are never changed automatically.';
  if (!changes.length) {
    alert('Nothing to apply — frame rate, GOP, bitrate and constant bitrate already match.\n\n' + note);
    return;
  }
  if (!confirm('Apply recommended settings to the camera?\n\nThis will change:\n' +
               changes.join('\n') + '\n\n' + note)) return;

  document.getElementById('cameraApplyBtn').disabled = true;
  const d = await postCameraWrite('/api/camera/settings/apply');
  if (!d.ok) {
    cameraSettingsActionResult = 'Apply failed: ' + (d.error || 'unknown error');
  } else {
    cameraSettingsActionResult =
      (d.changed.length ? 'Changed: ' + d.changed.join(', ') : 'Nothing changed') +
      (d.not_set.length ? ' · Not set: ' + d.not_set.join('; ') : '');
  }
  loadCameraSettingsPanel();
}

async function syncCameraClock(data) {
  const offset = data.settings.camera_clock_offset_s;
  if (!confirm('Sync the camera clock?\n\nCamera clock offset: ' + formatCameraClockOffset(offset) +
               ' → set to this laptop\'s current time.')) return;

  document.getElementById('cameraClockSyncBtn').disabled = true;
  const d = await postCameraWrite('/api/camera/clock/sync');
  cameraSettingsActionResult = d.ok
    ? 'Clock synced: offset ' + formatCameraClockOffset(d.before_offset_s) + ' → ' + formatCameraClockOffset(d.after_offset_s)
    : 'Clock sync failed: ' + (d.error || 'unknown error');
  loadCameraSettingsPanel();
}
