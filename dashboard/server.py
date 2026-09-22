#!/usr/bin/env python3
"""Minimal live dashboard for jev-trading paper books."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("JEV_OUT_ROOT", "/workspace/jev-trading/out")).resolve()
HOST = os.environ.get("JEV_DASH_HOST", "0.0.0.0")
PORT = int(os.environ.get("JEV_DASH_PORT", "8787"))

HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>jev-trading live</title>
<style>
  :root { --bg:#0b1020; --card:#151b2f; --text:#e8eefc; --muted:#9aa7c7; --ok:#3ddc97; --bad:#ff6b6b; --line:#243056; --accent:#6ea8fe; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background:var(--bg); color:var(--text); }
  header { padding:16px 20px; border-bottom:1px solid var(--line); display:flex; gap:16px; flex-wrap:wrap; align-items:baseline; }
  header h1 { font-size:18px; margin:0; font-weight:650; }
  header .meta { color:var(--muted); font-size:13px; }
  main { padding:16px; display:grid; gap:16px; }
  .grid { display:grid; gap:12px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; }
  .card h2 { margin:0 0 8px; font-size:14px; color:var(--accent); font-weight:650; letter-spacing:.02em; text-transform:uppercase; }
  .kpi { display:flex; justify-content:space-between; gap:8px; padding:6px 0; border-bottom:1px dashed var(--line); font-size:13px; }
  .kpi:last-child { border-bottom:0; }
  .kpi span { color:var(--muted); }
  .kpi b { font-variant-numeric: tabular-nums; }
  .pos { color:var(--ok); }
  .neg { color:var(--bad); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:8px 6px; border-bottom:1px solid var(--line); font-variant-numeric: tabular-nums; }
  th { color:var(--muted); font-weight:600; }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; background:#1d2744; color:var(--muted); font-size:12px; }
  .alive { color:var(--ok); }
  .dead { color:var(--bad); }
</style>
</head>
<body>
<header>
  <h1>jev-trading paper dashboard</h1>
  <div class="meta">auto-refresh 2s · dry-run only</div>
  <div class="meta" id="clock">—</div>
  <div class="meta" id="campaign">—</div>
</header>
<main>
  <div class="grid" id="markets"></div>
  <div class="card">
    <h2>Variant comparison (same Jev signal)</h2>
    <div class="meta" style="color:var(--muted);font-size:12px;margin-bottom:8px">primary = v_best · others = uncertain knobs</div>
    <h3 style="font-size:13px;color:var(--accent);margin:8px 0">Crypto</h3>
    <table>
      <thead><tr><th>Book</th><th>Gates / cap</th><th>Fills</th><th>PnL</th><th>Equity</th><th>Why</th></tr></thead>
      <tbody id="compare_crypto"></tbody>
    </table>
    <h3 style="font-size:13px;color:var(--accent);margin:16px 0 8px">Stock</h3>
    <table>
      <thead><tr><th>Book</th><th>Gates / cap</th><th>Fills</th><th>PnL</th><th>Equity</th><th>Why</th></tr></thead>
      <tbody id="compare_stock"></tbody>
    </table>
  </div>
  <div class="card">
    <h2>Latest answers</h2>
    <div class="grid" id="answers"></div>
  </div>
</main>
<script>
const fmt = (n, d=2) => (n==null || Number.isNaN(n)) ? '—' : Number(n).toFixed(d);
const pnlClass = (n) => (n>0 ? 'pos' : (n<0 ? 'neg' : ''));

function bookRows(live) {
  const rows = [];
  const primary = live.book || {};
  const th = live.thresholds || {};
  rows.push({
    id: primary.label || 'v_best',
    gates: {
      noul_min: primary.noul_min ?? th.noul_min,
      conf_min: primary.conf_min ?? th.conf_min,
      max_notional_usd: primary.max_notional_usd ?? th.max_notional_usd,
    },
    why: primary.why || 'primary',
    ...primary,
  });
  const shadows = live.shadows || {};
  for (const [id, s] of Object.entries(shadows)) {
    rows.push({
      id,
      gates: {
        noul_min: s.noul_min,
        conf_min: s.conf_min,
        max_notional_usd: s.max_notional_usd,
      },
      why: s.why || '',
      ...s,
    });
  }
  return rows;
}
function renderCompare(tbodyId, live) {
  const tbody = document.getElementById(tbodyId);
  tbody.innerHTML = bookRows(live).map(r => `<tr>
    <td>${r.id}</td>
    <td>≥${r.gates?.noul_min ?? '—'} / ≥${r.gates?.conf_min ?? '—'} · ≤$${r.gates?.max_notional_usd ?? '—'}</td>
    <td>${r.fills ?? 0}</td>
    <td class="${pnlClass(r.pnl)}">${fmt(r.pnl)}</td>
    <td>${fmt(r.equity)}</td>
    <td style="max-width:280px;color:var(--muted);font-size:12px">${r.why || '—'}</td>
  </tr>`).join('') || '<tr><td colspan="6">waiting for live.json</td></tr>';
}

function marketCard(name, live, alive) {
  const dist = live.decision_dist || {};
  return `<div class="card">
    <h2>${name} <span class="pill ${alive?'alive':'dead'}">${alive?'alive':'stopped'}</span></h2>
    <div class="kpi"><span>Ticks</span><b>${live.ticks_so_far ?? '—'}</b></div>
    <div class="kpi"><span>Latency avg</span><b>${fmt(live.latency_ms?.avg,1)} ms</b></div>
    <div class="kpi"><span>Decisions</span><b>B ${dist.buy||0} / S ${dist.sell||0} / H ${dist.hold||0}</b></div>
    <div class="kpi"><span>Last pick</span><b>${live.last_answers?.pick_symbol ?? '—'}</b></div>
    <div class="kpi"><span>Universe picks</span><b>${Object.entries(live.pick_dist||{}).map(([k,v])=>k+':'+v).slice(0,4).join(' ')||'—'}</b></div>
    <div class="kpi"><span>Primary fills</span><b>${live.book?.fills ?? 0}</b></div>
    <div class="kpi"><span>Primary PnL</span><b class="${pnlClass(live.book?.pnl)}">${fmt(live.book?.pnl)}</b></div>
    <div class="kpi"><span>Errors</span><b>${live.errors ?? 0}</b></div>
    <div class="kpi"><span>Last update</span><b>${live.last_ts ? new Date(live.last_ts).toLocaleString() : '—'}</b></div>
  </div>`;
}

async function refresh() {
  const res = await fetch('/api/snapshot');
  const data = await res.json();
  document.getElementById('clock').textContent = 'now ' + new Date(data.now).toLocaleString();
  const c = data.campaign || {};
  document.getElementById('campaign').textContent = c.ends_ts
    ? `ends ${new Date(c.ends_ts).toLocaleString()}`
    : 'no campaign meta';
  const markets = document.getElementById('markets');
  markets.innerHTML = '';
  for (const m of ['crypto','stock']) {
    const live = data.markets[m]?.live || {};
    const alive = !!data.markets[m]?.alive;
    markets.insertAdjacentHTML('beforeend', marketCard(m, live, alive));
  }
  renderCompare('compare_crypto', data.markets.crypto?.live || {});
  renderCompare('compare_stock', data.markets.stock?.live || {});

  const answers = document.getElementById('answers');
  answers.innerHTML = ['crypto','stock'].map(m => {
    const a = data.markets[m]?.live?.last_answers || {};
    return `<div class="card"><h2>${m} last</h2>
      <div class="kpi"><span>pick</span><b>${a.pick_symbol ?? '—'}</b></div>
      <div class="kpi"><span>move</span><b>${a.move ?? '—'}</b></div>
      <div class="kpi"><span>direction</span><b>${a.direction ?? '—'}</b></div>
      <div class="kpi"><span>noul</span><b>${fmt(a.should_trade,3)}</b></div>
      <div class="kpi"><span>dir_tail</span><b>${fmt(a.dir_tail,3)}</b></div>
      <div class="kpi"><span>toxicity</span><b>${fmt(a.toxicity,2)}</b></div>
      <div class="kpi"><span>size_usd</span><b>${fmt(a.size_usd,0)}</b></div>
      <div class="kpi"><span>edge</span><b>${fmt(a.edge_score,2)}</b></div>
    </div>`;
  }).join('');
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
'''


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def snapshot() -> dict:
    camp = read_json(ROOT / "campaign.json") or {}
    pids = read_json(ROOT / "campaign_pids.json") or {}
    markets = {}
    for m in ("crypto", "stock"):
        live = read_json(ROOT / m / "live.json") or {}
        meta = read_json(ROOT / m / "run_meta.json") or {}
        if meta.get("thresholds") and "thresholds" not in live:
            live["thresholds"] = meta.get("thresholds")
        markets[m] = {
            "live": live,
            "alive": process_alive(pids.get(m)),
            "pid": pids.get(m),
        }
    return {
        "now": datetime.now(timezone.utc).isoformat(),
        "campaign": camp,
        "markets": markets,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/snapshot":
            body = json.dumps(snapshot()).encode("utf-8")
            self._send(200, body, "application/json")
            return
        self._send(404, b"not found", "text/plain")


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"dashboard on http://{HOST}:{PORT}  out={ROOT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
