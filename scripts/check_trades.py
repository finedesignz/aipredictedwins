"""Query recent trades from the production Postgres DB."""
import json, subprocess, sys

# Get token
with open(r'C:\Users\artic\.claude\secrets\services.json') as f:
    secrets = json.load(f)
token = secrets['coolify']['api_token']

# Get DATABASE_URL from Coolify
import urllib.request
req = urllib.request.Request(
    'https://coolify.titaniumlabs.us/api/v1/applications/zkkw8wocws84gg4woc8kcoc4/envs',
    headers={'Authorization': f'Bearer {token}'}
)
with urllib.request.urlopen(req) as r:
    envs = json.load(r)

db_url = next((e['real_value'] for e in envs if e['key'] == 'DATABASE_URL'), None)
if not db_url:
    print("DATABASE_URL not found"); sys.exit(1)

print(f"Connecting to DB...")

import psycopg
from psycopg.rows import dict_row

with psycopg.connect(db_url, row_factory=dict_row) as conn:
    rows = conn.execute("""
        SELECT bot_id, symbol, side, qty::float, entry_price::float,
               exit_price::float, status, pnl::float,
               substring(timestamp::text, 1, 16) AS opened,
               substring(closed_at::text, 1, 16) AS closed
        FROM alpaca_trades
        ORDER BY timestamp DESC
        LIMIT 25
    """).fetchall()

    print(f"\n{'Bot':<5} {'Symbol':<10} {'Side':<5} {'Qty':>8} {'Entry':>9} {'Exit':>9} {'PnL':>9} {'Status':<12} {'Opened':<16} {'Closed'}")
    print("-" * 110)
    for r in rows:
        pnl_str = f"${r['pnl']:+.2f}" if r['pnl'] is not None else "open"
        exit_str = f"${r['exit_price']:.2f}" if r['exit_price'] else "-"
        print(f"{r['bot_id']:<5} {r['symbol']:<10} {r['side']:<5} {r['qty']:>8.4f} ${r['entry_price']:>8.2f} {exit_str:>9} {pnl_str:>9} {r['status']:<12} {r['opened'] or '-':<16} {r['closed'] or '-'}")

    # Summary
    total = len(rows)
    closed = [r for r in rows if r['status'] in ('closed','stopped','target_hit')]
    wins = [r for r in closed if (r['pnl'] or 0) > 0]
    total_pnl = sum(r['pnl'] or 0 for r in closed)
    open_pos = [r for r in rows if r['status'] == 'open']
    print(f"\n{total} trades shown | {len(open_pos)} open | {len(closed)} closed | {len(wins)}/{len(closed)} wins | Total PnL: ${total_pnl:+.2f}")
