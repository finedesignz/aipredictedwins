"""Compute BTC vs 50DMA — determines whether Bot C trend strategy should hold or exit BITX."""
import json, urllib.request

with open(r'C:\Users\artic\.claude\secrets\services.json') as f:
    token = json.load(f)['coolify']['api_token']
req = urllib.request.Request(
    'https://coolify.titaniumlabs.us/api/v1/applications/zkkw8wocws84gg4woc8kcoc4/envs',
    headers={'Authorization': f'Bearer {token}'})
with urllib.request.urlopen(req) as r:
    envs = json.load(r)
ev = {e['key']: e['real_value'] for e in envs}
H = {'APCA-API-KEY-ID': ev['ALPACA_API_KEY_C'], 'APCA-API-SECRET-KEY': ev['ALPACA_SECRET_KEY_C']}

# Daily BTC bars from Alpaca crypto data API
import datetime
start = (datetime.date.today() - datetime.timedelta(days=80)).isoformat()
url = ('https://data.alpaca.markets/v1beta3/crypto/us/bars'
       f'?symbols=BTC%2FUSD&timeframe=1Day&limit=200&start={start}')
rq = urllib.request.Request(url, headers=H)
with urllib.request.urlopen(rq, timeout=30) as r:
    data = json.load(r)
bars = data['bars']['BTC/USD']
closes = [b['c'] for b in bars]
print(f"BTC daily bars: {len(closes)}, range {bars[0]['t'][:10]}..{bars[-1]['t'][:10]}")
for n in (50,):
    if len(closes) >= n:
        ma = sum(closes[-n:]) / n
        price = closes[-1]
        print(f"BTC=${price:,.0f}  {n}DMA=${ma:,.0f}  -> {'ABOVE (hold BITX)' if price>ma else 'BELOW (SELL BITX)'}")
print(f"Last 7 closes: {[round(c) for c in closes[-7:]]}")

# BITX recent price
url2 = ('https://data.alpaca.markets/v2/stocks/bars'
        '?symbols=BITX&timeframe=1Day&limit=10')
rq2 = urllib.request.Request(url2, headers=H)
with urllib.request.urlopen(rq2, timeout=30) as r:
    d2 = json.load(r)
bb = d2.get('bars', {}).get('BITX', [])
print(f"BITX last closes: {[round(b['c'],2) for b in bb]}")
