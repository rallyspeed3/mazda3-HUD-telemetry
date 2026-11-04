#pragma once

// Single-page web UI, served from flash -- no internet connection needed
// (everything is inline, no CDN links). Talks to the handful of JSON
// endpoints registered in esp32_web_logger.ino.
const char INDEX_HTML[] PROGMEM = R"HTMLPAGE(
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mazda3 Telemetry</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px;
    font-family: -apple-system, system-ui, Segoe UI, Roboto, sans-serif;
    background: #121212; color: #eee;
  }
  h1 { font-size: 1.2rem; margin: 0 0 16px; }
  .card {
    background: #1e1e1e; border-radius: 10px; padding: 14px 16px;
    margin-bottom: 14px;
  }
  .stats {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
  }
  .stat { text-align: center; }
  .stat .val { font-size: 1.5rem; font-weight: 600; }
  .stat .label { font-size: 0.72rem; color: #999; text-transform: uppercase; }
  #recBtn {
    width: 100%; padding: 14px; font-size: 1.05rem; font-weight: 600;
    border: none; border-radius: 10px; color: #fff; cursor: pointer;
  }
  #recBtn.start { background: #2e7d32; }
  #recBtn.stop { background: #c62828; }
  #recStatus { text-align: center; margin-top: 8px; font-size: 0.85rem; color: #999; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th, td { text-align: left; padding: 8px 4px; border-bottom: 1px solid #333; }
  th { color: #999; font-weight: 500; font-size: 0.75rem; text-transform: uppercase; }
  .actions a, .actions button {
    color: #8ab4f8; background: none; border: none; cursor: pointer;
    font-size: 0.8rem; padding: 2px 6px; text-decoration: none;
  }
  .actions button.danger { color: #e57373; }
  .small { font-size: 0.75rem; color: #999; }
  .toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .toolbar button { background: #333; color: #eee; border: none; border-radius: 6px; padding: 6px 10px; font-size: 0.8rem; }
</style>
</head>
<body>

<h1>Mazda3 Telemetry</h1>

<div class="card">
  <div class="stats">
    <div class="stat"><div class="val" id="s_rpm">--</div><div class="label">RPM</div></div>
    <div class="stat"><div class="val" id="s_speed">--</div><div class="label">Speed (mph)</div></div>
    <div class="stat"><div class="val" id="s_gear">--</div><div class="label">Gear</div></div>
    <div class="stat"><div class="val" id="s_throttle">--</div><div class="label">Throttle %</div></div>
    <div class="stat"><div class="val" id="s_brake">--</div><div class="label">Brake</div></div>
    <div class="stat"><div class="val" id="s_steer">--</div><div class="label">Steering</div></div>
  </div>
</div>

<div class="card">
  <button id="recBtn" class="start" onclick="toggleRecording()">Start Recording</button>
  <div id="recStatus">not recording</div>
</div>

<div class="card">
  <div class="toolbar">
    <strong>Logs</strong>
    <button onclick="refreshLogs()">Refresh</button>
  </div>
  <table>
    <thead><tr><th>Name</th><th>Size</th><th></th></tr></thead>
    <tbody id="logRows"><tr><td colspan="3" class="small">loading...</td></tr></tbody>
  </table>
</div>

<script>
let recording = false;

function fmtSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + " KB";
  return (bytes/1024/1024).toFixed(2) + " MB";
}

async function pollLive() {
  try {
    const r = await fetch('/api/live');
    const j = await r.json();
    document.getElementById('s_rpm').textContent = j.rpm;
    document.getElementById('s_speed').textContent = j.speed.toFixed(1);
    document.getElementById('s_gear').textContent = j.reverse ? "R" : (j.gear === 0 ? "N" : j.gear);
    document.getElementById('s_throttle').textContent = j.throttle.toFixed(0);
    document.getElementById('s_brake').textContent = j.brake;
    document.getElementById('s_steer').textContent = j.steering.toFixed(0) + "°";

    recording = j.recording;
    const btn = document.getElementById('recBtn');
    const status = document.getElementById('recStatus');
    btn.textContent = recording ? "Stop Recording" : "Start Recording";
    btn.className = recording ? "stop" : "start";
    status.textContent = recording ? `recording "${j.log_name}" -- ${j.log_rows} rows` : "not recording";
  } catch (e) { /* ESP32 momentarily busy -- just retry next tick */ }
}

async function toggleRecording() {
  const path = recording ? '/api/record/stop' : '/api/record/start';
  await fetch(path, { method: 'POST' });
  pollLive();
  setTimeout(refreshLogs, 300);
}

async function refreshLogs() {
  const r = await fetch('/api/logs');
  const logs = await r.json();
  const tbody = document.getElementById('logRows');
  if (logs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" class="small">No logs yet</td></tr>';
    return;
  }
  tbody.innerHTML = logs.map(l => `
    <tr>
      <td>${l.name}</td>
      <td class="small">${fmtSize(l.size)}</td>
      <td class="actions">
        <a href="/api/logs/download?name=${encodeURIComponent(l.name)}">download</a>
        <button onclick="renameLog('${l.name}')">rename</button>
        <button class="danger" onclick="deleteLog('${l.name}')">delete</button>
      </td>
    </tr>`).join('');
}

async function renameLog(name) {
  const next = prompt("Rename " + name + " to:", name);
  if (!next || next === name) return;
  const body = new URLSearchParams({ name: name, new: next });
  const r = await fetch('/api/logs/rename', { method: 'POST', body: body });
  const j = await r.json();
  if (!j.ok) alert(j.error || "Rename failed");
  refreshLogs();
}

async function deleteLog(name) {
  if (!confirm("Delete " + name + "? This can't be undone.")) return;
  const body = new URLSearchParams({ name: name });
  const r = await fetch('/api/logs/delete', { method: 'POST', body: body });
  const j = await r.json();
  if (!j.ok) alert(j.error || "Delete failed");
  refreshLogs();
}

setInterval(pollLive, 250);
pollLive();
refreshLogs();
setInterval(refreshLogs, 4000);
</script>
</body>
</html>
)HTMLPAGE";
