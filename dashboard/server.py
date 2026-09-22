#!/usr/bin/env python3
"""Trading-desk live dashboard for jev-trading paper books."""
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
<title>jev-trading desk</title>
<style>
  :root {
    --bg:#070b14; --panel:#0e1524; --panel2:#121a2c; --line:#1e2a44;
    --text:#e8eefc; --muted:#8b9bb8; --ok:#22c55e; --bad:#ef4444;
    --buy:#22c55e; --sell:#ef4444; --hold:#94a3b8; --accent:#60a5fa;
    --flash-up:rgba(34,197,94,.22); --flash-dn:rgba(239,68,68,.22);
  }
  * { box-sizing: border-box; }
  body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background:var(--bg); color:var(--text); }
  header {
    padding:12px 16px; border-bottom:1px solid var(--line);
    display:flex; gap:14px; flex-wrap:wrap; align-items:center; justify-content:space-between;
    background:linear-gradient(180deg, #0c1322, #070b14);
  }
  header .left { display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; }
  header h1 { font-size:16px; margin:0; font-weight:700; letter-spacing:.02em; }
  header .meta { color:var(--muted); font-size:12px; }
  .tabs { display:flex; gap:6px; }
  .tab {
    border:1px solid var(--line); background:var(--panel); color:var(--muted);
    border-radius:999px; padding:6px 12px; font-size:12px; cursor:pointer;
  }
  .tab.active { color:var(--text); border-color:#33507e; background:#152038; }
  main { padding:12px; display:grid; gap:12px; }
  .row { display:grid; gap:12px; grid-template-columns: repeat(4, minmax(0,1fr)); }
  @media (max-width:1100px) { .row { grid-template-columns: repeat(2, minmax(0,1fr)); } }
  @media (max-width:700px) { .row { grid-template-columns: 1fr; } }
  .ticker {
    background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:12px 14px;
    transition: background .35s ease;
  }
  .ticker.flash-up { background:var(--flash-up); }
  .ticker.flash-dn { background:var(--flash-dn); }
  .ticker .label { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
  .ticker .value { margin-top:4px; font-size:28px; font-weight:700; font-variant-numeric:tabular-nums; line-height:1.1; }
  .ticker .sub { margin-top:4px; color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }
  .pos { color:var(--ok); } .neg { color:var(--bad); }
  .desk { display:grid; gap:12px; grid-template-columns: 1.2fr 1fr; }
  @media (max-width:1000px) { .desk { grid-template-columns: 1fr; } }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:12px; overflow:hidden; }
  .card .hd {
    padding:10px 12px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:center;
    background:var(--panel2);
  }
  .card .hd h2 { margin:0; font-size:13px; font-weight:650; letter-spacing:.03em; text-transform:uppercase; color:var(--accent); }
  .card .bd { padding:0; max-height:360px; overflow:auto; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); font-variant-numeric:tabular-nums; white-space:nowrap; }
  th { color:var(--muted); font-weight:600; position:sticky; top:0; background:var(--panel); }
  .side-buy { color:var(--buy); font-weight:700; }
  .side-sell { color:var(--sell); font-weight:700; }
  .side-hold { color:var(--hold); font-weight:700; }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; background:#1a243a; color:var(--muted); font-size:11px; }
  .pill.alive { color:var(--ok); border:1px solid rgba(34,197,94,.35); }
  .pill.dead { color:var(--bad); border:1px solid rgba(239,68,68,.35); }
  .signal {
    display:grid; gap:8px; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    padding:12px;
  }
  .signal .cell { background:#0b1220; border:1px solid var(--line); border-radius:10px; padding:10px; }
  .signal .cell .k { color:var(--muted); font-size:11px; text-transform:uppercase; }
  .signal .cell .v { margin-top:4px; font-size:16px; font-weight:650; font-variant-numeric:tabular-nums; }
  .muted { color:var(--muted); }
  .tiny { font-size:11px; color:var(--muted); }
  .compare-wrap { padding:8px 10px 12px; }
  .blink-row { animation: blink 1s ease; }
  @keyframes blink { from { background: rgba(96,165,250,.18);} to { background: transparent; } }
</style>
</head>
<body>
<header>
  <div class="left">
    <h1>JEV 交易台 · 纸面</h1>
    <div class="meta">实时刷新 1s</div>
    <div class="meta" id="clock">—</div>
    <div class="meta" id="campaign">—</div>
    <span class="pill" id="alivePill">—</span>
  </div>
  <div class="tabs">
    <button class="tab active" data-m="crypto">Crypto</button>
    <button class="tab" data-m="stock">Stock</button>
  </div>
</header>
<main>
  <div class="row" id="tickers"></div>
  <div class="card">
    <div class="hd"><h2>当前信号</h2><span class="tiny" id="lastTs">—</span></div>
    <div class="signal" id="signal"></div>
  </div>
  <div class="desk">
    <div class="card">
      <div class="hd"><h2>成交流水</h2><span class="tiny">买 / 卖 · 标的 · 金额</span></div>
      <div class="bd"><table>
        <thead><tr><th>时间/Tick</th><th>方向</th><th>标的</th><th>价格</th><th>数量</th><th>金额 $</th><th>Move</th></tr></thead>
        <tbody id="tape"></tbody>
      </table></div>
    </div>
    <div class="card">
      <div class="hd"><h2>当前持仓</h2><span class="tiny" id="posCount">—</span></div>
      <div class="bd"><table>
        <thead><tr><th>标的</th><th>方向</th><th>数量</th><th>现价</th><th>成本</th><th>市值 $</th><th>浮盈亏</th></tr></thead>
        <tbody id="positions"></tbody>
      </table></div>
    </div>
  </div>
  <div class="card">
    <div class="hd"><h2>对照账本</h2><span class="tiny">同一 Jev 信号 · 不同执行规则</span></div>
    <div class="compare-wrap">
      <table>
        <thead><tr><th>账本</th><th>门槛 / 上限</th><th>成交数</th><th>PnL</th><th>权益</th><th>现金</th><th>说明</th></tr></thead>
        <tbody id="compare"></tbody>
      </table>
    </div>
  </div>
</main>
<script>
let market = 'crypto';
let prev = { equity: null, pnl: null, cash: null, fillKey: null };

const fmt = (n, d=2) => (n==null || Number.isNaN(Number(n))) ? '—' : Number(n).toFixed(d);
const money = (n) => (n==null || Number.isNaN(Number(n))) ? '—' : Number(n).toLocaleString(undefined,{minimumFractionDigits:2, maximumFractionDigits:2});
const pnlClass = (n) => (n>0 ? 'pos' : (n<0 ? 'neg' : ''));
const sideClass = (s) => s==='buy'||s==='long' ? 'side-buy' : (s==='sell'||s==='short' ? 'side-sell' : 'side-hold');

document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    market = btn.dataset.m;
    prev = { equity: null, pnl: null, cash: null, fillKey: null };
    refresh();
  });
});

function flashTicker(el, next, prevVal) {
  if (prevVal==null || next==null) return;
  el.classList.remove('flash-up','flash-dn');
  void el.offsetWidth;
  if (next > prevVal) el.classList.add('flash-up');
  else if (next < prevVal) el.classList.add('flash-dn');
}

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
  for (const [id, s] of Object.entries(live.shadows || {})) {
    rows.push({
      id,
      gates: { noul_min: s.noul_min, conf_min: s.conf_min, max_notional_usd: s.max_notional_usd },
      why: s.why || '',
      ...s,
    });
  }
  return rows;
}

function render(data) {
  const m = data.markets[market] || {};
  const live = m.live || {};
  const book = live.book || {};
  const a = live.last_answers || {};
  const alive = !!m.alive;

  document.getElementById('clock').textContent = new Date(data.now).toLocaleString();
  const c = data.campaign || {};
  document.getElementById('campaign').textContent = c.ends_ts
    ? ('结束 ' + new Date(c.ends_ts).toLocaleString())
    : '无 campaign';
  const pill = document.getElementById('alivePill');
  pill.textContent = alive ? (market + ' 运行中') : (market + ' 已停');
  pill.className = 'pill ' + (alive ? 'alive' : 'dead');
  document.getElementById('lastTs').textContent = live.last_ts ? new Date(live.last_ts).toLocaleString() : '—';

  const equity = book.equity, pnl = book.pnl, cash = book.cash, fills = book.fills;
  document.getElementById('tickers').innerHTML = `
    <div class="ticker" id="tEquity"><div class="label">权益 Equity</div><div class="value">$${money(equity)}</div><div class="sub">ticks ${live.ticks_so_far ?? 0}</div></div>
    <div class="ticker" id="tPnl"><div class="label">总盈亏 PnL</div><div class="value ${pnlClass(pnl)}">${pnl>0?'+':''}${money(pnl)}</div><div class="sub">主账本 v_best</div></div>
    <div class="ticker" id="tCash"><div class="label">现金 Cash</div><div class="value">$${money(cash)}</div><div class="sub">可用购买力</div></div>
    <div class="ticker" id="tFills"><div class="label">成交笔数</div><div class="value">${fills ?? 0}</div><div class="sub">B ${(live.decision_dist||{}).buy||0} / S ${(live.decision_dist||{}).sell||0} / H ${(live.decision_dist||{}).hold||0}</div></div>
  `;
  flashTicker(document.getElementById('tEquity'), equity, prev.equity);
  flashTicker(document.getElementById('tPnl'), pnl, prev.pnl);
  flashTicker(document.getElementById('tCash'), cash, prev.cash);
  prev.equity = equity; prev.pnl = pnl; prev.cash = cash;

  const side = a.direction || '—';
  document.getElementById('signal').innerHTML = `
    <div class="cell"><div class="k">标的</div><div class="v">${a.pick_symbol ?? '—'}</div></div>
    <div class="cell"><div class="k">动作</div><div class="v ${sideClass(side)}">${(side||'—').toUpperCase()}</div></div>
    <div class="cell"><div class="k">金额 $</div><div class="v">${money(a.size_usd)}</div></div>
    <div class="cell"><div class="k">Move</div><div class="v">${a.move ?? '—'}</div></div>
    <div class="cell"><div class="k">Noul</div><div class="v">${fmt(a.should_trade,3)}</div></div>
    <div class="cell"><div class="k">Dir Tail</div><div class="v">${fmt(a.dir_tail,3)}</div></div>
    <div class="cell"><div class="k">Toxicity</div><div class="v">${fmt(a.toxicity,2)}</div></div>
    <div class="cell"><div class="k">Edge</div><div class="v">${fmt(a.edge_score,2)}</div></div>
  `;

  // tape: prefer book.recent_fills, else derive from API tape
  const tape = (book.recent_fills && book.recent_fills.length)
    ? book.recent_fills.slice().reverse()
    : (m.tape || []);
  const last = tape[0];
  const fillKey = last ? `${last.i}-${last.symbol}-${last.side}-${last.notional_usd}` : null;
  document.getElementById('tape').innerHTML = tape.length ? tape.map((f, idx) => `
    <tr class="${idx===0 && fillKey && fillKey!==prev.fillKey ? 'blink-row' : ''}">
      <td>#${f.i ?? '—'}</td>
      <td class="${sideClass(f.side)}">${(f.side||'').toUpperCase()}</td>
      <td><b>${f.symbol || '—'}</b></td>
      <td>${fmt(f.px, f.px!=null && f.px<1 ? 6 : 4)}</td>
      <td>${fmt(f.qty, f.qty!=null && Math.abs(f.qty)>1000 ? 2 : 6)}</td>
      <td><b>$${money(f.notional_usd)}</b></td>
      <td class="muted">${f.move || '—'}</td>
    </tr>
  `).join('') : `<tr><td colspan="7" class="muted">暂无成交</td></tr>`;
  prev.fillKey = fillKey;

  const pos = book.positions_detail || [];
  document.getElementById('posCount').textContent = pos.length ? (pos.length + ' 个标的') : '空仓';
  document.getElementById('positions').innerHTML = pos.length ? pos.map(p => `
    <tr>
      <td><b>${p.symbol}</b></td>
      <td class="${sideClass(p.side)}">${(p.side||'').toUpperCase()}</td>
      <td>${fmt(p.qty, Math.abs(p.qty)>1000 ? 2 : 6)}</td>
      <td>${fmt(p.mid, p.mid!=null && p.mid<1 ? 6 : 4)}</td>
      <td>${fmt(p.avg_entry, p.avg_entry!=null && p.avg_entry<1 ? 6 : 4)}</td>
      <td>$${money(p.notional_usd)}</td>
      <td class="${pnlClass(p.unrealized_pnl)}">${p.unrealized_pnl>0?'+':''}${money(p.unrealized_pnl)}</td>
    </tr>
  `).join('') : `<tr><td colspan="7" class="muted">当前空仓</td></tr>`;

  document.getElementById('compare').innerHTML = bookRows(live).map(r => `
    <tr>
      <td><b>${r.id}</b></td>
      <td>≥${r.gates?.noul_min ?? '—'} / ≥${r.gates?.conf_min ?? '—'} · ≤$${r.gates?.max_notional_usd ?? '—'}</td>
      <td>${r.fills ?? 0}</td>
      <td class="${pnlClass(r.pnl)}">${r.pnl>0?'+':''}${money(r.pnl)}</td>
      <td>$${money(r.equity)}</td>
      <td>$${money(r.cash)}</td>
      <td class="tiny" style="white-space:normal;max-width:320px">${r.why || '—'}</td>
    </tr>
  `).join('') || `<tr><td colspan="7" class="muted">等待 live.json</td></tr>`;
}

async function refresh() {
  try {
    const res = await fetch('/api/snapshot');
    const data = await res.json();
    render(data);
  } catch (e) {
    document.getElementById('clock').textContent = '刷新失败';
  }
}
refresh();
setInterval(refresh, 1000);
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


def tape_from_recent(path: Path) -> list[dict]:
    recent = read_json(path) or []
    out = []
    for t in recent:
        f = t.get("fill")
        if not f:
            continue
        out.append(
            {
                "symbol": f.get("symbol") or t.get("selected_symbol"),
                "side": f.get("side"),
                "px": f.get("px"),
                "qty": f.get("qty"),
                "notional_usd": f.get("notional_usd"),
                "i": f.get("i") or t.get("i"),
                "move": f.get("move") or (t.get("answers") or {}).get("move"),
                "ts": t.get("ts"),
                "book": f.get("book"),
            }
        )
    out.reverse()  # newest first
    return out[:40]


def snapshot() -> dict:
    camp = read_json(ROOT / "campaign.json") or {}
    pids = read_json(ROOT / "campaign_pids.json") or {}
    markets = {}
    for m in ("crypto", "stock"):
        live = read_json(ROOT / m / "live.json") or {}
        meta = read_json(ROOT / m / "run_meta.json") or {}
        if meta.get("thresholds") and "thresholds" not in live:
            live["thresholds"] = meta.get("thresholds")
        # fallback tape if checkpoint not yet enriched
        book = live.get("book") or {}
        tape = book.get("recent_fills") or tape_from_recent(ROOT / m / "recent_ticks.json")
        markets[m] = {
            "live": live,
            "alive": process_alive(pids.get(m)),
            "pid": pids.get(m),
            "tape": tape,
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
