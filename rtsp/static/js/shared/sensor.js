export function toggleSensor() {
  const btn = document.getElementById('sensorToggle');
  const panel = document.getElementById('sensorPanel');
  const on = btn.getAttribute('aria-checked') === 'true';
  btn.setAttribute('aria-checked', on ? 'false' : 'true');
  panel.classList.toggle('open', !on);
}
export function onProtocolChange() {
  const proto = document.getElementById('sProtocol').value;
  document.getElementById('sRtuRow').style.display = proto === 'modbus_rtu' ? '' : 'none';
  document.getElementById('sTcpRow').style.display = proto === 'modbus_tcp' ? '' : 'none';
}
export async function testSensor() {
  const cfg = buildSensorConfig();
  const status = document.getElementById('sensorTestStatus');
  status.className = 'sensor-test-status';
  status.textContent = 'Testing…';
  try {
    const res = await fetch('/api/sensor/test', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(cfg)
    });
    const data = await res.json();
    if (data.ok) {
      status.className = 'sensor-test-status ok';
      status.textContent = `✓ ${data.value_m.toFixed(3)} m`;
    } else {
      status.className = 'sensor-test-status err';
      status.textContent = '✗ ' + data.error;
    }
  } catch {
    status.className = 'sensor-test-status err';
    status.textContent = '✗ Network error';
  }
}
export function buildSensorConfig() {
  const proto = document.getElementById('sProtocol').value;
  const cfg = {
    protocol: proto,
    slave_id: parseInt(document.getElementById('sSlaveId').value) || 1,
    address: document.getElementById('sAddress').value.trim(),
    register_type: document.getElementById('sRegType').value,
    scale_factor: parseFloat(document.getElementById('sScale').value) || 0.1,
    unit: document.getElementById('sUnit').value,
  };
  if (proto === 'modbus_rtu') {
    cfg.com_port = document.getElementById('sComPort').value.trim();
    cfg.baud_rate = parseInt(document.getElementById('sBaud').value);
    cfg.parity = document.getElementById('sParity').value;
  } else {
    cfg.tcp_host = document.getElementById('sTcpHost').value.trim();
    cfg.tcp_port = parseInt(document.getElementById('sTcpPort').value) || 502;
  }
  return cfg;
}

fetch('/api/sensor/config').then(r => r.ok ? r.json() : {}).then(cfg => {
  if (cfg.protocol) {
    document.getElementById('sProtocol').value = cfg.protocol || 'modbus_rtu';
    onProtocolChange();
    if (cfg.com_port)    document.getElementById('sComPort').value = cfg.com_port;
    if (cfg.baud_rate)   document.getElementById('sBaud').value    = String(cfg.baud_rate);
    if (cfg.parity)      document.getElementById('sParity').value  = cfg.parity;
    if (cfg.tcp_host)    document.getElementById('sTcpHost').value = cfg.tcp_host;
    if (cfg.tcp_port)    document.getElementById('sTcpPort').value = String(cfg.tcp_port);
    if (cfg.slave_id)    document.getElementById('sSlaveId').value = String(cfg.slave_id);
    if (cfg.address != null) document.getElementById('sAddress').value = String(cfg.address);
    if (cfg.scale_factor) document.getElementById('sScale').value  = String(cfg.scale_factor);
    if (cfg.unit)        document.getElementById('sUnit').value    = cfg.unit;
  }
}).catch(() => {});
