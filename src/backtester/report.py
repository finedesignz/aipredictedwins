"""HTML report generator for backtest results. No external dependencies."""
from __future__ import annotations

import json
import os
from datetime import datetime


def generate_report(
    phase: int,
    config_dict: dict,
    summary: dict,
    equity_curve: list[float],
    trade_history: list[dict],
    output_dir: str = "data/backtest_results",
) -> str:
    """Write an HTML report and return the file path."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"phase{phase}_{ts}.html"
    path = os.path.join(output_dir, fname)

    eq_json = json.dumps(equity_curve)

    # Build trade rows safely (no f-string with arbitrary user data in class attr)
    trade_rows = ""
    for t in trade_history:
        pnl = t.get("pnl", 0)
        cls = "pos" if pnl >= 0 else "neg"
        trade_rows += (
            f"<tr><td>{t.get('symbol','')}</td>"
            f"<td>${t.get('entry_price',0):,.2f}</td>"
            f"<td>${t.get('exit_price',0):,.2f}</td>"
            f"<td>{t.get('qty',0):.4f}</td>"
            f'<td class="{cls}">${pnl:+,.2f}</td>'
            f"<td>{t.get('reason','')}</td></tr>\n"
        )

    monitor_pnl = summary.get("monitor_pnl", 0)
    total_return = summary.get("total_return_pct", 0)
    monitor_cls = "pos" if monitor_pnl >= 0 else "neg"
    total_return_cls = "pos" if total_return >= 0 else "neg"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Backtest Phase {phase} — {ts}</title>
<style>
  body {{ font-family: monospace; max-width: 900px; margin: 2rem auto; background: #0d1117; color: #e6edf3; }}
  h1, h2 {{ color: #58a6ff; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1rem; }}
  th {{ background: #161b22; padding: 8px; text-align: left; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #30363d; }}
  .pos {{ color: #3fb950; }} .neg {{ color: #f85149; }}
  canvas {{ background: #161b22; border-radius: 6px; margin: 1rem 0; }}
</style>
</head>
<body>
<h1>Backtest Report — Phase {phase}</h1>
<p>Generated: {datetime.now().isoformat()[:19]}</p>

<h2>Summary</h2>
<table>
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td>Trade count</td><td>{summary.get("trade_count", 0)}</td></tr>
  <tr><td>Monitor P&amp;L</td>
      <td class="{monitor_cls}">${monitor_pnl:,.2f}</td></tr>
  <tr><td>Win rate</td><td>{summary.get("win_rate", 0):.1%}</td></tr>
  <tr><td>Sharpe ratio</td><td>{summary.get("sharpe_ratio", 0):.3f}</td></tr>
  <tr><td>Max drawdown</td><td class="neg">{summary.get("max_drawdown", 0):.2%}</td></tr>
  <tr><td>Total return</td>
      <td class="{total_return_cls}">{total_return:+.2f}%</td></tr>
  <tr><td>Final equity</td><td>${summary.get("final_equity", 0):,.2f}</td></tr>
</table>

<h2>Equity Curve</h2>
<canvas id="chart" width="880" height="300"></canvas>
<script>
const eq = {eq_json};
const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');
const w = canvas.width, h = canvas.height, pad = 20;
const mn = Math.min(...eq), mx = Math.max(...eq);
const sy = (v) => pad + (1 - (v - mn) / (mx - mn || 1)) * (h - 2*pad);
const sx = (i) => pad + i / (eq.length - 1) * (w - 2*pad);
ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 1.5; ctx.beginPath();
eq.forEach((v,i) => i === 0 ? ctx.moveTo(sx(i), sy(v)) : ctx.lineTo(sx(i), sy(v)));
ctx.stroke();
</script>

<h2>Config</h2>
<pre>{json.dumps(config_dict, indent=2)}</pre>

<h2>Trade History</h2>
<table>
  <tr><th>Symbol</th><th>Entry</th><th>Exit</th><th>Qty</th><th>P&amp;L</th><th>Reason</th></tr>
  {trade_rows}
</table>
</body></html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
