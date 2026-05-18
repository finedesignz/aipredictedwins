"""Switch Bot A/B to equities (with inverse-ETF coverage for downside).

Steps:
  1. Close any stale crypto positions on A and B (regime change).
  2. PUT /api/bots/A — conservative equity config.
  3. PUT /api/bots/B — aggressive equity config.
  4. Verify.

Inverse ETFs (SQQQ, SH, BITI, SOXS) let the bots go LONG when the market
is bearish — no Alpaca shorting permission needed.
"""
import json, urllib.request, urllib.error, time

with open(r'C:\Users\artic\.claude\secrets\services.json') as f:
    coolify_token = json.load(f)['coolify']['api_token']

req = urllib.request.Request(
    'https://coolify.titaniumlabs.us/api/v1/applications/zkkw8wocws84gg4woc8kcoc4/envs',
    headers={'Authorization': f'Bearer {coolify_token}'})
with urllib.request.urlopen(req) as r:
    envs = json.load(r)
ev = {e['key']: e['real_value'] for e in envs}
DASH = ev['DASHBOARD_TOKEN']

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
BASE = 'https://app.aipredictedwins.com'
ALPACA = 'https://paper-api.alpaca.markets'

def aclose_all(bot_id: str):
    key = ev.get(f'ALPACA_API_KEY_{bot_id}')
    sec = ev.get(f'ALPACA_SECRET_KEY_{bot_id}')
    if not key:
        print(f"[{bot_id}] no env keys, skip"); return
    H = {'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': sec}
    rq = urllib.request.Request(f'{ALPACA}/v2/positions', headers=H)
    with urllib.request.urlopen(rq, timeout=20) as r:
        pos = json.load(r)
    print(f"[{bot_id}] {len(pos)} open positions before switch")
    for p in pos:
        sym = p['symbol']
        rq = urllib.request.Request(
            f'{ALPACA}/v2/positions/{sym}', headers=H, method='DELETE')
        try:
            with urllib.request.urlopen(rq, timeout=20) as r:
                o = json.load(r)
                print(f"  close {sym}: {o.get('status')} qty={o.get('qty')}")
        except urllib.error.HTTPError as e:
            print(f"  close {sym}: ERROR {e.code} {e.read()[:120]}")

def put_bot(bot_id: str, body: dict):
    data = json.dumps(body).encode()
    rq = urllib.request.Request(
        f'{BASE}/api/bots/{bot_id}', data=data, method='PUT',
        headers={'Authorization': f'Bearer {DASH}', 'User-Agent': UA,
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(rq, timeout=30) as r:
            d = json.load(r)
            return d.get('data', d)
    except urllib.error.HTTPError as e:
        return {'_error': f'{e.code} {e.read()[:300]}'}

# 1. Clear stale crypto positions
print("=== STEP 1: close stale positions ===")
for bid in ('A', 'B'):
    aclose_all(bid)
print("\n(waiting 5s for fills)")
time.sleep(5)

# Equity universe: liquid large-caps + inverse ETFs for downside capture
STOCK_UNIV = ('SPY,QQQ,DIA,IWM,NVDA,AAPL,MSFT,TSLA,META,AMZN,GOOGL,AMD,'
              'COIN,MSTR,'           # crypto-correlated equity proxies
              'SQQQ,SH,SDS,SOXS,'    # inverse / leveraged-inverse
              'TQQQ,SPXL,SOXL')      # leveraged-long (for bullish regimes)

# 2. Update A — conservative
print("\n=== STEP 2: PUT /api/bots/A ===")
print(put_bot('A', {
    'asset_class': 'stock',
    'stock_universe': STOCK_UNIV,
    'min_confluence': 4,        # tighter than B
    'min_short_confluence': 4,  # if shorts are attempted, require strong signal
    'rsi_ceiling': 65.0,
    'max_position_pct': 0.05,
    'kelly_fraction': 0.25,
    'skip_risk_gate': False,
    'enabled': True,
}))

# 3. Update B — aggressive
print("\n=== STEP 3: PUT /api/bots/B ===")
print(put_bot('B', {
    'asset_class': 'stock',
    'stock_universe': STOCK_UNIV,
    'min_confluence': 3,
    'min_short_confluence': 3,
    'rsi_ceiling': 72.0,
    'max_position_pct': 0.10,
    'kelly_fraction': 0.50,
    'skip_risk_gate': True,
    'enabled': True,
}))

# 4. Verify
print("\n=== STEP 4: verify ===")
rq = urllib.request.Request(
    f'{BASE}/api/bots',
    headers={'Authorization': f'Bearer {DASH}', 'User-Agent': UA})
with urllib.request.urlopen(rq) as r:
    bots = json.load(r)
for b in bots.get('data', []):
    if b['bot_id'] in ('A', 'B'):
        print({k: b.get(k) for k in (
            'bot_id', 'asset_class', 'strategy', 'min_confluence',
            'min_short_confluence', 'rsi_ceiling', 'max_position_pct',
            'kelly_fraction', 'skip_risk_gate', 'enabled', 'status')})
