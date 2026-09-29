const RECORDER_STALL_AGE_S = 20;
const RECORDER_FIRST_PIECE_GRACE_S = 30;
let recorderRunningSince = null;

function formatRecorderSeconds(s) {
  s = Math.round(s);
  return s < 60 ? s + ' s' : Math.floor(s / 60) + ' min ' + (s % 60) + ' s';
}

export function renderRecorderStatusLine(data) {
  const el = document.getElementById('recorderStatus');
  if (!data.running) {
    recorderRunningSince = null;
    el.className = 'recorder-status idle';
    el.textContent = 'Recorder idle';
    return;
  }
  if (recorderRunningSince === null) recorderRunningSince = Date.now();

  const age = data.newest_piece_age_s;
  const waitedS = (Date.now() - recorderRunningSince) / 1000;
  const stalled = age != null ? age > RECORDER_STALL_AGE_S : waitedS > RECORDER_FIRST_PIECE_GRACE_S;
  const restarts = data.restarts > 0
    ? ` (${data.restarts} restart${data.restarts === 1 ? '' : 's'})` : '';

  if (stalled) {
    el.className = 'recorder-status stalled';
    el.textContent = '● Recorder stalled — ' + (data.last_error || 'no new video') + restarts;
  } else {
    el.className = 'recorder-status ok';
    el.textContent = '● Recording · ' + formatRecorderSeconds(data.buffered_s || 0) + ' buffered · ' +
      (age != null ? `newest piece ${Math.round(age)} s ago` : 'waiting for first piece') + restarts;
  }
}

export async function pollRecorderStatus() {
  let data;
  try {
    const res = await fetch('/api/stream/recorder_status');
    data = await res.json();
  } catch { return; }
  renderRecorderStatusLine(data);
}

export function startRecorderStatusPolling() {
  pollRecorderStatus();
  setInterval(pollRecorderStatus, 3000);
}
