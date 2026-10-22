"""
Telegram Cloner & Topic Engine - Web Dashboard & Mini App Frontend
Provides modern, responsive glassmorphic UI for managing userbot operations.
"""

def get_webapp_html():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>TeleCloner Pro - Dashboard & Mini App</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: rgba(22, 30, 49, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --card-hover: rgba(30, 41, 67, 0.85);
      --primary: #3b82f6;
      --primary-glow: rgba(59, 130, 246, 0.35);
      --accent: #8b5cf6;
      --accent-glow: rgba(139, 92, 246, 0.35);
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --radius: 16px;
      --radius-sm: 10px;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-tap-highlight-color: transparent;
    }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Outfit', sans-serif;
      min-height: 100vh;
      overflow-x: hidden;
      background-image: 
        radial-gradient(circle at 15% 15%, rgba(59, 130, 246, 0.15) 0%, transparent 40%),
        radial-gradient(circle at 85% 85%, rgba(139, 92, 246, 0.15) 0%, transparent 40%);
      background-attachment: fixed;
    }

    .container {
      max-width: 900px;
      margin: 0 auto;
      padding: 20px 16px 80px 16px;
    }

    /* Header */
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 0 24px 0;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 24px;
    }

    .logo-area {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .logo-icon {
      width: 42px;
      height: 42px;
      border-radius: 12px;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
      box-shadow: 0 4px 14px var(--primary-glow);
    }

    .logo-text h1 {
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }

    .logo-text span {
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 0.8rem;
      font-weight: 600;
      background: rgba(16, 185, 129, 0.1);
      color: var(--success);
      border: 1px solid rgba(16, 185, 129, 0.25);
    }

    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--success);
      box-shadow: 0 0 8px var(--success);
      animation: pulse 2s infinite;
    }

    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.5; transform: scale(0.85); }
    }

    /* Cards */
    .card {
      background: var(--card-bg);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 22px;
      margin-bottom: 20px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
      transition: all 0.2s ease;
    }

    .card-title {
      font-size: 1.05rem;
      font-weight: 600;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 10px;
    }

    /* Form Inputs */
    .form-group {
      margin-bottom: 16px;
    }

    .form-row {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 12px;
    }

    @media (max-width: 600px) {
      .form-row {
        grid-template-columns: 1fr;
      }
    }

    label {
      display: block;
      font-size: 0.85rem;
      color: var(--text-muted);
      margin-bottom: 6px;
      font-weight: 500;
    }

    input[type="text"], input[type="number"], select {
      width: 100%;
      padding: 12px 14px;
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid var(--card-border);
      border-radius: var(--radius-sm);
      color: var(--text);
      font-family: 'Outfit', sans-serif;
      font-size: 0.95rem;
      transition: border-color 0.2s, box-shadow 0.2s;
    }

    input:focus, select:focus {
      outline: none;
      border-color: var(--primary);
      box-shadow: 0 0 0 3px var(--primary-glow);
    }

    /* Buttons */
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 12px 20px;
      font-size: 0.95rem;
      font-weight: 600;
      border-radius: var(--radius-sm);
      cursor: pointer;
      border: none;
      transition: all 0.2s;
      width: 100%;
    }

    .btn-primary {
      background: linear-gradient(135deg, var(--primary), var(--accent));
      color: white;
      box-shadow: 0 4px 16px var(--primary-glow);
    }

    .btn-primary:hover {
      opacity: 0.95;
      transform: translateY(-1px);
    }

    .btn-secondary {
      background: rgba(255, 255, 255, 0.08);
      color: var(--text);
      border: 1px solid var(--card-border);
    }

    .btn-secondary:hover {
      background: rgba(255, 255, 255, 0.12);
    }

    .btn-danger {
      background: rgba(239, 68, 68, 0.15);
      color: var(--danger);
      border: 1px solid rgba(239, 68, 68, 0.3);
    }

    .btn-sm {
      padding: 8px 14px;
      font-size: 0.85rem;
      width: auto;
    }

    .actions-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-top: 14px;
    }

    @media (max-width: 600px) {
      .actions-grid {
        grid-template-columns: repeat(2, 1fr);
      }
    }

    /* Stats Grid */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-bottom: 20px;
    }

    .stat-box {
      background: rgba(15, 23, 42, 0.5);
      border: 1px solid var(--card-border);
      border-radius: var(--radius-sm);
      padding: 14px;
      text-align: center;
    }

    .stat-val {
      font-size: 1.4rem;
      font-weight: 700;
      color: var(--text);
      margin-top: 4px;
    }

    .stat-lbl {
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    /* Analysis Box */
    .analysis-card {
      background: rgba(139, 92, 246, 0.06);
      border: 1px solid rgba(139, 92, 246, 0.25);
      border-radius: var(--radius);
      padding: 20px;
      margin-top: 16px;
      display: none;
    }

    .text-list {
      max-height: 240px;
      overflow-y: auto;
      margin-top: 14px;
      padding-right: 6px;
    }

    .text-item {
      background: rgba(15, 23, 42, 0.7);
      border: 1px solid var(--card-border);
      border-radius: var(--radius-sm);
      padding: 10px 12px;
      margin-bottom: 8px;
      display: flex;
      align-items: flex-start;
      gap: 12px;
      font-size: 0.85rem;
      cursor: pointer;
      transition: background 0.15s;
    }

    .text-item:hover {
      background: rgba(30, 41, 67, 0.8);
    }

    .text-item input[type="checkbox"] {
      margin-top: 3px;
      width: 16px;
      height: 16px;
      accent-color: var(--accent);
      cursor: pointer;
    }

    .text-snippet {
      flex: 1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      color: #e2e8f0;
    }

    .text-meta {
      font-size: 0.7rem;
      color: var(--text-muted);
      font-family: 'JetBrains Mono', monospace;
    }

    /* Radio pills */
    .radio-pills {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-top: 10px;
    }

    .radio-pill {
      display: block;
      text-align: center;
      padding: 8px;
      border-radius: var(--radius-sm);
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid var(--card-border);
      font-size: 0.82rem;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
    }

    .radio-pill.active {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
      box-shadow: 0 2px 10px var(--accent-glow);
    }

    /* Toggle switch */
    .toggle-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 0;
      border-bottom: 1px solid var(--card-border);
    }

    .toggle-row:last-child {
      border-bottom: none;
    }

    .switch {
      position: relative;
      display: inline-block;
      width: 44px;
      height: 24px;
    }

    .switch input {
      opacity: 0;
      width: 0;
      height: 0;
    }

    .slider {
      position: absolute;
      cursor: pointer;
      top: 0; left: 0; right: 0; bottom: 0;
      background-color: rgba(255, 255, 255, 0.15);
      transition: .3s;
      border-radius: 34px;
    }

    .slider:before {
      position: absolute;
      content: "";
      height: 18px;
      width: 18px;
      left: 3px;
      bottom: 3px;
      background-color: white;
      transition: .3s;
      border-radius: 50%;
    }

    input:checked + .slider {
      background-color: var(--primary);
    }

    input:checked + .slider:before {
      transform: translateX(20px);
    }

    /* Terminal output */
    .terminal {
      background: #060911;
      border: 1px solid var(--card-border);
      border-radius: var(--radius-sm);
      padding: 14px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8rem;
      color: #38bdf8;
      max-height: 160px;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-all;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="logo-area">
        <div class="logo-icon">⚡</div>
        <div class="logo-text">
          <h1>TeleCloner Pro</h1>
          <span>MTProto History Engine</span>
        </div>
      </div>
      <div class="status-badge" id="status-badge">
        <span class="status-dot" id="status-dot"></span>
        <span id="status-text">Idle</span>
      </div>
    </header>

    <!-- Live Stats Card -->
    <div class="stats-grid">
      <div class="stat-box">
        <div class="stat-lbl">Transferred</div>
        <div class="stat-val" id="stat-transferred">0</div>
      </div>
      <div class="stat-box">
        <div class="stat-lbl">Queue Items</div>
        <div class="stat-val" id="stat-queue">0</div>
      </div>
      <div class="stat-box">
        <div class="stat-lbl">Batch Size</div>
        <div class="stat-val">100 msgs</div>
      </div>
    </div>

    <!-- Source & Analysis Card -->
    <div class="card">
      <div class="card-title">📤 1. Source & Topic Analysis</div>
      <div class="form-row">
        <div class="form-group">
          <label>Source Chat Link or ID (-100... or 220...)</label>
          <input type="text" id="src-input" placeholder="e.g. -1002200390931 or https://t.me/c/2200390931/899">
        </div>
        <div class="form-group">
          <label>Topic ID (Optional)</label>
          <input type="number" id="src-topic" placeholder="e.g. 899">
        </div>
      </div>
      <button class="btn btn-secondary" id="btn-scan" onclick="scanSource()">
        <span>🔍 Scan & Analyze Text Posts</span>
      </button>

      <!-- Analysis Results Popup Area -->
      <div class="analysis-card" id="analysis-box">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div style="font-weight:600; font-size:0.95rem;" id="analysis-summary">📊 Analysis Results</div>
          <span style="font-size:0.75rem; color:var(--text-muted);" id="analysis-count">0 Text Posts</span>
        </div>

        <div style="margin-top:12px;">
          <label>Text Message Pinning Action in Destination:</label>
          <div class="radio-pills">
            <div class="radio-pill active" id="pill-none" onclick="setPinMode('none')">Don't Pin</div>
            <div class="radio-pill" id="pill-all" onclick="setPinMode('all')">Pin All Text</div>
            <div class="radio-pill" id="pill-custom" onclick="setPinMode('custom')">Custom Pick</div>
          </div>
        </div>

        <div class="text-list" id="text-items-list">
          <!-- Text messages rendered dynamically -->
        </div>
      </div>
    </div>

    <!-- Destination & Execution Card -->
    <div class="card">
      <div class="card-title">📥 2. Destination & Options</div>
      <div class="form-row">
        <div class="form-group">
          <label>Destination Chat Link or ID (-100...)</label>
          <input type="text" id="dest-input" placeholder="e.g. -1003992974528 or https://t.me/c/3992974528/6850">
        </div>
        <div class="form-group">
          <label>Destination Topic ID</label>
          <input type="number" id="dest-topic" placeholder="e.g. 6850">
        </div>
      </div>

      <div class="form-row">
        <div class="form-group">
          <label>Delivery Mode</label>
          <select id="mode-select">
            <option value="here">Post into specified topic/root (Here)</option>
            <option value="new">Create new forum topic per item (New)</option>
          </select>
        </div>
        <div class="form-group">
          <label>Range (Start–End ID, Optional)</label>
          <input type="text" id="range-input" placeholder="e.g. 100-500">
        </div>
      </div>

      <div style="margin: 12px 0;">
        <div class="toggle-row">
          <div>
            <div style="font-size:0.9rem; font-weight:500;">Delete Checkpoint Header on Finish</div>
            <div style="font-size:0.75rem; color:var(--text-muted);">Leaves destination completely clean when transfer completes</div>
          </div>
          <label class="switch">
            <input type="checkbox" id="toggle-clean-header" checked>
            <span class="slider"></span>
          </label>
        </div>
      </div>

      <button class="btn btn-primary" id="btn-start" onclick="startClone()" style="margin-top:10px;">
        <span>🚀 Start 100-Batch Transfer</span>
      </button>
    </div>

    <!-- Live Controls & Terminal -->
    <div class="card">
      <div class="card-title">🎮 3. Pipeline Controls & Live Status</div>
      <div class="actions-grid">
        <button class="btn btn-secondary btn-sm" onclick="triggerAction('pause')">⏸️ Pause</button>
        <button class="btn btn-secondary btn-sm" onclick="triggerAction('resume')">▶️ Resume</button>
        <button class="btn btn-secondary btn-sm" onclick="triggerAction('stop')">🛑 Stop</button>
        <button class="btn btn-danger btn-sm" onclick="triggerAction('purge')">🗑️ Purge Last</button>
      </div>

      <div style="margin-top:16px;">
        <label>Engine Output</label>
        <div class="terminal" id="terminal-out">Connecting to Userbot engine...</div>
      </div>
    </div>
  </div>

  <script>
    let currentPinMode = 'none';
    let analyzedData = null;
    let selectedTextIds = new Set();

    async function fetchStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        document.getElementById('stat-transferred').textContent = data.total_sent_count || 0;
        document.getElementById('stat-queue').textContent = (data.queue || []).length;
        
        const badge = document.getElementById('status-badge');
        const dot = document.getElementById('status-dot');
        const txt = document.getElementById('status-text');

        if (data.is_running) {
          txt.textContent = data.is_paused ? 'Paused' : 'Transferring';
          badge.style.color = data.is_paused ? 'var(--warning)' : 'var(--primary)';
          dot.style.background = data.is_paused ? 'var(--warning)' : 'var(--primary)';
        } else {
          txt.textContent = 'Idle';
          badge.style.color = 'var(--success)';
          dot.style.background = 'var(--success)';
        }

        if (data.dest_link && !document.getElementById('dest-input').value) {
          document.getElementById('dest-input').value = data.dest_link;
        }

        const term = document.getElementById('terminal-out');
        term.textContent = `Status: ${data.current_status || 'Idle'}\nActive Task: ${data.active_task ? data.active_task.title : 'None'}\nQueue Index: ${data.queue_index || 0}/${(data.queue || []).length}`;
      } catch (err) {
        console.error('Status fetch error:', err);
      }
    }

    function setPinMode(mode) {
      currentPinMode = mode;
      document.getElementById('pill-none').className = 'radio-pill ' + (mode === 'none' ? 'active' : '');
      document.getElementById('pill-all').className = 'radio-pill ' + (mode === 'all' ? 'active' : '');
      document.getElementById('pill-custom').className = 'radio-pill ' + (mode === 'custom' ? 'active' : '');

      const checkboxes = document.querySelectorAll('.text-item input[type="checkbox"]');
      checkboxes.forEach(cb => {
        if (mode === 'all') cb.checked = true;
        if (mode === 'none') cb.checked = false;
      });
      updateSelectedIds();
    }

    function updateSelectedIds() {
      selectedTextIds.clear();
      document.querySelectorAll('.text-item input[type="checkbox"]:checked').forEach(cb => {
        selectedTextIds.add(parseInt(cb.value));
      });
    }

    async function scanSource() {
      const src = document.getElementById('src-input').value.trim();
      const topic = document.getElementById('src-topic').value.trim();
      if (!src) {
        alert('Please enter a source chat ID or link first.');
        return;
      }

      const btn = document.getElementById('btn-scan');
      btn.innerHTML = '<span>⏳ Analyzing source in MTProto...</span>';
      btn.disabled = true;

      try {
        const res = await fetch('/api/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source: src, topic_id: topic ? parseInt(topic) : null })
        });
        const data = await res.json();
        if (!data.success) {
          alert('Error analyzing source: ' + data.error);
          return;
        }

        analyzedData = data;
        const box = document.getElementById('analysis-box');
        box.style.display = 'block';

        document.getElementById('analysis-summary').textContent = `📊 Found ${data.total_messages} messages (${data.media_count} media, ${data.text_count} text)`;
        document.getElementById('analysis-count').textContent = `${data.text_count} text posts`;

        const list = document.getElementById('text-items-list');
        list.innerHTML = '';

        if (data.text_messages.length === 0) {
          list.innerHTML = '<div style="color:var(--text-muted); padding:10px; text-align:center;">No pure text messages found in this topic.</div>';
        } else {
          data.text_messages.forEach(item => {
            const row = document.createElement('div');
            row.className = 'text-item';
            row.innerHTML = `
              <input type="checkbox" value="${item.id}" onchange="updateSelectedIds();">
              <div style="flex:1;">
                <div class="text-snippet">${escapeHtml(item.snippet)}</div>
                <div class="text-meta">Msg ID: ${item.id} • ${item.date || ''} • ${item.length} chars</div>
              </div>
            `;
            list.appendChild(row);
          });
        }
      } catch (e) {
        alert('Scan request failed: ' + e);
      } finally {
        btn.innerHTML = '<span>🔍 Scan & Analyze Text Posts</span>';
        btn.disabled = false;
      }
    }

    async function startClone() {
      const src = document.getElementById('src-input').value.trim();
      const srcTopic = document.getElementById('src-topic').value.trim();
      const dest = document.getElementById('dest-input').value.trim();
      const destTopic = document.getElementById('dest-topic').value.trim();
      const mode = document.getElementById('mode-select').value;
      const cleanHeader = document.getElementById('toggle-clean-header').checked;
      const range = document.getElementById('range-input').value.trim();

      if (!src) { alert('Please enter source'); return; }
      if (!dest) { alert('Please enter destination'); return; }

      updateSelectedIds();

      const payload = {
        source: src,
        source_topic_id: srcTopic ? parseInt(srcTopic) : null,
        destination: dest,
        destination_topic_id: destTopic ? parseInt(destTopic) : null,
        mode: mode,
        range: range,
        clean_header: cleanHeader,
        pin_mode: currentPinMode,
        pinned_ids: Array.from(selectedTextIds),
        pure_text_ids: analyzedData ? analyzedData.text_messages.map(m => m.id) : []
      };

      const btn = document.getElementById('btn-start');
      btn.innerHTML = '<span>⏳ Starting Pipeline...</span>';
      btn.disabled = true;

      try {
        const res = await fetch('/api/clone', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const resp = await res.json();
        if (resp.success) {
          alert('🚀 Clone pipeline started successfully!');
          fetchStatus();
        } else {
          alert('Error starting clone: ' + resp.error);
        }
      } catch (err) {
        alert('Failed to connect to API: ' + err);
      } finally {
        btn.innerHTML = '<span>🚀 Start 100-Batch Transfer</span>';
        btn.disabled = false;
      }
    }

    async function triggerAction(action) {
      try {
        const res = await fetch('/api/' + action, { method: 'POST' });
        const data = await res.json();
        fetchStatus();
      } catch (e) {
        alert('Action error: ' + e);
      }
    }

    function escapeHtml(str) {
      if (!str) return '';
      return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    setInterval(fetchStatus, 3000);
    fetchStatus();
  </script>
</body>
</html>"""
