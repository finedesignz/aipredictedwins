"""Diagnose why no trades placed in 144h — via dashboard API (DB host is Coolify-internal)."""
import json, urllib.request, urllib.error

with open(r'C:\Users\artic\.claude\secrets\services.json') as f:
    token = json.load(f)['coolify']['api_token']

req = urllib.request.Request(
    'https://coolify.titaniumlabs.us/api/v1/applications/zkkw8wocws84gg4woc8kcoc4/envs',
    headers={'Authorization': f'Bearer {token}'})
with urllib.request.urlopen(req) as r:
    envs = json.load(r)
dash = next((e['real_value'] for e in envs if e['key'] == 'DASHBOARD_TOKEN'), None)
print(f"DASHBOARD_TOKEN found: {bool(dash)}")

BASE = 'https://app.aipredictedwins.com'
H = {'Authorization': f'Bearer {dash}',
     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}

def get(path):
    try:
        rq = urllib.request.Request(BASE + path, headers=H)
        with urllib.request.urlopen(rq, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {'_error': f'{e.code} {e.read()[:200]}'}
    except Exception as e:
        return {'_error': str(e)[:200]}

print("\n=== BOTS ===")
bots = get('/api/bots')
for b in (bots.get('data') or []):
    print({k: b.get(k) for k in ('bot_id','label','strategy','enabled','status',
          'status_detail','min_confluence','rsi_ceiling','asset_class','thread_alive')})
if '_error' in bots:
    print(bots)

for bot in ('A', 'B', 'C'):
    print(f"\n=== PORTFOLIO {bot} ===")
    print(get(f'/api/portfolio?bot={bot}'))

print("\n=== RECENT TRADES (all) ===")
tr = get('/api/trades?limit=12')
for t in (tr.get('data') or [])[:12]:
    print({k: t.get(k) for k in ('bot','symbol','side','status','pnl','timestamp')})
if '_error' in tr:
    print(tr)

print("\n=== SIGNALS ===")
print(get('/api/signals'))

print("\n=== SETTINGS (cycle info) ===")
s = get('/api/settings')
if 'data' in s:
    d = s['data']
    print({k: d.get(k) for k in ('running','last_cycle','cycle_count','uptime_seconds','health')})
else:
    print(s)
