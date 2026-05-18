import json, urllib.request

with open(r'C:\Users\artic\.claude\secrets\services.json') as f:
    token = json.load(f)['coolify']['api_token']

deploy_id = "j6ev0pexylicx58hsdbxsfkl"
req = urllib.request.Request(
    f"https://coolify.titaniumlabs.us/api/v1/deployments/{deploy_id}",
    headers={"Authorization": f"Bearer {token}"}
)
with urllib.request.urlopen(req) as r:
    d = json.load(r)

logs = d.get('logs', [])
if isinstance(logs, str):
    logs = json.loads(logs)

for entry in logs:
    if not isinstance(entry, dict): continue
    out = entry.get('output', '')
    typ = entry.get('type', '')
    if typ == 'stderr' or any(k in out for k in ['error','Error','Traceback','seed','migration','WARNING','not healthy','failed','Exception']):
        print(f"[{typ}] {out}")
