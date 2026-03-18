#!/usr/bin/env python3
"""Web Dashboard for Trading Alert Bot.

Provides a live browser-based dashboard showing:
- Bot status and configuration
- Real-time alerts feed
- Monitored symbols
- Signal activity and confidence scores
- API key status

Run standalone:  python dashboard.py
Or integrated:   python main.py --dashboard
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string

logger = logging.getLogger("trading_bot.dashboard")

# ---------------------------------------------------------------------------
# Shared state (thread-safe via deque + simple reads)
# ---------------------------------------------------------------------------

@dataclass
class DashboardState:
    bot_running: bool = False
    dry_run: bool = False
    start_time: str = ""
    symbols_count: int = 0
    symbols: list = field(default_factory=list)
    alerts: deque = field(default_factory=lambda: deque(maxlen=100))
    alerts_sent_total: int = 0
    signals_detected: int = 0
    last_signal_time: str = ""
    sentiment_cache: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)


state = DashboardState()


def record_alert(alert_data: dict):
    """Called by the bot to push an alert into the dashboard feed."""
    alert_data["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    state.alerts.appendleft(alert_data)
    state.alerts_sent_total += 1
    state.last_signal_time = alert_data["timestamp"]


def record_signal():
    """Called by the bot when any signal is detected (even below threshold)."""
    state.signals_detected += 1
    state.last_signal_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


def _check_api_keys() -> list[dict]:
    """Check which API keys are configured."""
    load_dotenv(Path(__file__).resolve().parent / ".env")
    keys = [
        {"name": "Binance API Key", "env": "BINANCE_API_KEY", "required": False},
        {"name": "Binance API Secret", "env": "BINANCE_API_SECRET", "required": False},
        {"name": "Markets.com API Key", "env": "MARKETS_COM_API_KEY", "required": False},
        {"name": "Markets.com API Secret", "env": "MARKETS_COM_API_SECRET", "required": False},
        {"name": "Telegram Bot Token", "env": "TELEGRAM_BOT_TOKEN", "required": True},
        {"name": "Telegram Chat ID", "env": "TELEGRAM_CHAT_ID", "required": True},
        {"name": "Twilio Account SID", "env": "TWILIO_ACCOUNT_SID", "required": False},
        {"name": "Twilio Auth Token", "env": "TWILIO_AUTH_TOKEN", "required": False},
        {"name": "NewsAPI Key", "env": "NEWSAPI_KEY", "required": False},
        {"name": "Finnhub API Key", "env": "FINNHUB_API_KEY", "required": False},
        {"name": "Alpha Vantage Key", "env": "ALPHA_VANTAGE_KEY", "required": False},
        {"name": "CryptoPanic API Key", "env": "CRYPTOPANIC_API_KEY", "required": False},
    ]
    for k in keys:
        val = os.getenv(k["env"], "")
        k["configured"] = bool(val and val.strip())
        k["masked"] = (val[:4] + "****" + val[-4:]) if len(val) > 8 else ("****" if val else "")
    return keys


def _load_config() -> dict:
    config_path = Path(__file__).resolve().parent / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/status")
def api_status():
    uptime = ""
    if state.start_time:
        try:
            started = datetime.strptime(state.start_time, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - started
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime = f"{hours}h {minutes}m {seconds}s"
        except Exception:
            uptime = "N/A"

    return jsonify({
        "bot_running": state.bot_running,
        "dry_run": state.dry_run,
        "start_time": state.start_time,
        "uptime": uptime,
        "symbols_count": state.symbols_count,
        "alerts_sent_total": state.alerts_sent_total,
        "signals_detected": state.signals_detected,
        "last_signal_time": state.last_signal_time,
    })


@app.route("/api/alerts")
def api_alerts():
    return jsonify(list(state.alerts))


@app.route("/api/symbols")
def api_symbols():
    return jsonify(state.symbols[:200])


@app.route("/api/config")
def api_config():
    cfg = _load_config()
    # Redact nothing — config has no secrets
    return jsonify(cfg)


@app.route("/api/keys")
def api_keys():
    return jsonify(_check_api_keys())


@app.route("/api/sentiment")
def api_sentiment():
    return jsonify(dict(state.sentiment_cache))


# ---------------------------------------------------------------------------
# HTML Template — Single-page dark dashboard
# ---------------------------------------------------------------------------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading Alert Bot — Dashboard</title>
<style>
  :root {
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --yellow: #d29922;
    --orange: #db6d28;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,-apple-system,sans-serif; font-size:14px; }
  a { color:var(--accent); text-decoration:none; }

  .header { background:var(--card); border-bottom:1px solid var(--border); padding:16px 24px; display:flex; align-items:center; justify-content:space-between; }
  .header h1 { font-size:20px; font-weight:600; }
  .header .badge { padding:4px 12px; border-radius:12px; font-size:12px; font-weight:600; }
  .badge-running { background:var(--green); color:#000; }
  .badge-stopped { background:var(--red); color:#fff; }
  .badge-dry { background:var(--yellow); color:#000; }

  .container { max-width:1400px; margin:0 auto; padding:20px 24px; }

  .grid { display:grid; gap:16px; }
  .grid-4 { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }
  .grid-2 { grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); }

  .card { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:16px; }
  .card h2 { font-size:14px; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; margin-bottom:12px; }
  .card .big-num { font-size:32px; font-weight:700; }

  .stat-label { color:var(--muted); font-size:12px; margin-top:4px; }

  .alert-item { padding:12px; border-bottom:1px solid var(--border); }
  .alert-item:last-child { border-bottom:none; }
  .alert-item .symbol { font-weight:700; font-size:16px; }
  .alert-item .dir-long { color:var(--green); }
  .alert-item .dir-short { color:var(--red); }
  .alert-item .meta { color:var(--muted); font-size:12px; margin-top:4px; }
  .alert-item .confidence { float:right; font-size:18px; font-weight:700; }

  .key-row { display:flex; align-items:center; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--border); }
  .key-row:last-child { border-bottom:none; }
  .key-name { font-weight:500; }
  .key-status { font-size:12px; padding:2px 8px; border-radius:8px; }
  .key-ok { background:var(--green); color:#000; }
  .key-missing { background:var(--border); color:var(--muted); }

  .config-pre { background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:12px; font-size:12px; font-family:'Fira Code',monospace; overflow-x:auto; max-height:400px; overflow-y:auto; color:var(--muted); white-space:pre-wrap; }

  .symbol-grid { display:flex; flex-wrap:wrap; gap:6px; max-height:300px; overflow-y:auto; }
  .symbol-chip { background:var(--bg); border:1px solid var(--border); padding:4px 10px; border-radius:4px; font-size:12px; font-family:monospace; }

  .refresh-note { text-align:center; color:var(--muted); font-size:11px; margin-top:16px; }

  .empty { color:var(--muted); font-style:italic; padding:20px; text-align:center; }

  .progress-bar { width:100%; height:6px; background:var(--border); border-radius:3px; margin-top:4px; }
  .progress-fill { height:100%; border-radius:3px; transition:width 0.3s; }

  .section-title { font-size:18px; font-weight:600; margin:24px 0 12px; }

  @media (max-width:600px) {
    .grid-2 { grid-template-columns:1fr; }
    .header { flex-direction:column; gap:8px; }
  }
</style>
</head>
<body>

<div class="header">
  <h1>Trading Alert Bot</h1>
  <div>
    <span id="badge-status" class="badge badge-stopped">OFFLINE</span>
    <span id="badge-mode" class="badge" style="display:none"></span>
  </div>
</div>

<div class="container">

  <!-- Stats Row -->
  <div class="grid grid-4" style="margin-bottom:16px">
    <div class="card">
      <h2>Symbols Monitored</h2>
      <div class="big-num" id="stat-symbols">0</div>
      <div class="stat-label">across all exchanges</div>
    </div>
    <div class="card">
      <h2>Alerts Sent</h2>
      <div class="big-num" id="stat-alerts">0</div>
      <div class="stat-label">total this session</div>
    </div>
    <div class="card">
      <h2>Signals Detected</h2>
      <div class="big-num" id="stat-signals">0</div>
      <div class="stat-label">including below threshold</div>
    </div>
    <div class="card">
      <h2>Uptime</h2>
      <div class="big-num" id="stat-uptime" style="font-size:24px">--</div>
      <div class="stat-label" id="stat-start">not started</div>
    </div>
  </div>

  <!-- Main Content -->
  <div class="grid grid-2">

    <!-- Alerts Feed -->
    <div class="card" style="max-height:500px;overflow-y:auto">
      <h2>Live Alerts Feed</h2>
      <div id="alerts-container">
        <div class="empty">No alerts yet. Waiting for signals...</div>
      </div>
    </div>

    <!-- API Keys Status -->
    <div class="card">
      <h2>API Key Status</h2>
      <div id="keys-container">
        <div class="empty">Loading...</div>
      </div>
    </div>

  </div>

  <div class="grid grid-2" style="margin-top:16px">

    <!-- Symbols -->
    <div class="card">
      <h2>Monitored Symbols</h2>
      <div id="symbols-container" class="symbol-grid">
        <div class="empty">Bot not running — no symbols loaded</div>
      </div>
    </div>

    <!-- Config -->
    <div class="card">
      <h2>Active Configuration</h2>
      <pre id="config-container" class="config-pre">Loading...</pre>
    </div>

  </div>

  <p class="refresh-note">Auto-refreshes every 3 seconds</p>

</div>

<script>
async function fetchJSON(url) {
  try { const r = await fetch(url); return await r.json(); }
  catch(e) { return null; }
}

async function refresh() {
  // Status
  const s = await fetchJSON('/api/status');
  if (s) {
    const badge = document.getElementById('badge-status');
    const modeBadge = document.getElementById('badge-mode');
    if (s.bot_running) {
      badge.textContent = 'RUNNING';
      badge.className = 'badge badge-running';
    } else {
      badge.textContent = 'OFFLINE';
      badge.className = 'badge badge-stopped';
    }
    if (s.dry_run) {
      modeBadge.style.display = '';
      modeBadge.textContent = 'DRY RUN';
      modeBadge.className = 'badge badge-dry';
    } else {
      modeBadge.style.display = 'none';
    }
    document.getElementById('stat-symbols').textContent = s.symbols_count;
    document.getElementById('stat-alerts').textContent = s.alerts_sent_total;
    document.getElementById('stat-signals').textContent = s.signals_detected;
    document.getElementById('stat-uptime').textContent = s.uptime || '--';
    document.getElementById('stat-start').textContent = s.start_time ? 'started ' + s.start_time : 'not started';
  }

  // Alerts
  const alerts = await fetchJSON('/api/alerts');
  const ac = document.getElementById('alerts-container');
  if (alerts && alerts.length > 0) {
    ac.innerHTML = alerts.map(a => `
      <div class="alert-item">
        <span class="confidence">${a.confidence || '?'}%</span>
        <div class="symbol">${a.symbol} <span class="${a.direction==='LONG'?'dir-long':'dir-short'}">${a.direction}</span></div>
        <div>${a.signal_type || ''} &mdash; ${a.description || ''}</div>
        <div class="meta">${a.exchange || ''} &bull; ${a.asset_class || ''} &bull; ${a.timestamp || ''}</div>
      </div>
    `).join('');
  } else if (alerts && alerts.length === 0) {
    ac.innerHTML = '<div class="empty">No alerts yet. Waiting for signals...</div>';
  }

  // Keys
  const keys = await fetchJSON('/api/keys');
  const kc = document.getElementById('keys-container');
  if (keys) {
    kc.innerHTML = keys.map(k => `
      <div class="key-row">
        <span class="key-name">${k.name}</span>
        <span class="key-status ${k.configured?'key-ok':'key-missing'}">${k.configured ? 'Configured' : 'Missing'}</span>
      </div>
    `).join('');
  }

  // Symbols
  const syms = await fetchJSON('/api/symbols');
  const sc = document.getElementById('symbols-container');
  if (syms && syms.length > 0) {
    sc.innerHTML = syms.map(s => {
      const name = typeof s === 'string' ? s : (s.symbol || s.name || JSON.stringify(s));
      return `<span class="symbol-chip">${name}</span>`;
    }).join('');
  }

  // Config
  const cfg = await fetchJSON('/api/config');
  if (cfg) {
    document.getElementById('config-container').textContent = JSON.stringify(cfg, null, 2);
  }
}

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

def start_dashboard(host: str = "0.0.0.0", port: int = 5050):
    """Start the dashboard in a background thread (non-blocking)."""
    def _run():
        app.run(host=host, port=port, debug=False, use_reloader=False)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logger.info("Dashboard running at http://%s:%d", host, port)
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print("\n  Dashboard starting at http://localhost:5050\n")
    app.run(host="0.0.0.0", port=5050, debug=True)
