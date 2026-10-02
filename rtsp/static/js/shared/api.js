export const API = '';

export function streamLiveUrl(rtspUrl) {
  return '/api/stream/live?rtsp_url=' + encodeURIComponent(rtspUrl);
}
export function streamSnapshot(rtspUrl) {
  return fetch('/api/stream/snapshot?rtsp_url=' + encodeURIComponent(rtspUrl));
}
export function streamProbe(rtspUrl) {
  return fetch(`${API}/api/stream/probe?rtsp_url=` + encodeURIComponent(rtspUrl));
}
export function streamStart(fd) {
  return fetch(`${API}/api/stream/start`, { method: 'POST', body: fd });
}
export function streamStop() {
  return fetch(`${API}/api/stream/stop`, { method: 'POST' });
}
export function streamStatus() {
  return fetch(`${API}/api/stream/status`);
}
export function streamConfig(body) {
  return fetch(`${API}/api/stream/config`, {
    method: 'PATCH', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
}
export function streamRecordStart(body) {
  if (body === undefined) {
    return fetch(`${API}/api/stream/record/start`, { method: 'POST' });
  }
  return fetch(`${API}/api/stream/record/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
export function streamRecordStop() {
  return fetch(`${API}/api/stream/record/stop`, { method: 'POST' });
}
export function streamRecordSnapshot(body) {
  return fetch('/api/stream/record_snapshot', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
export function streamSnapshotStatus() {
  return fetch('/api/stream/snapshot_status');
}
export function streamSaveBatch() {
  return fetch('/api/stream/save_batch', { method: 'POST' });
}

export function sensorTest(cfg) {
  return fetch('/api/sensor/test', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(cfg)
  });
}
export function sensorConfig() {
  return fetch('/api/sensor/config');
}

export function staticFirstFrame(fd) {
  return fetch('/api/static/first_frame', { method: 'POST', body: fd });
}
export function processPipeline(fd) {
  return fetch('/api/process', { method: 'POST', body: fd });
}
export function jobStatus(jobId) {
  return fetch(`/api/status/${jobId}`);
}
