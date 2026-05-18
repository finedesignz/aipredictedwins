"""Add Bot C Alpaca keys to Coolify env vars."""
import json, urllib.request, urllib.error

with open(r'C:\Users\artic\.claude\secrets\services.json') as f:
    secrets = json.load(f)
token = secrets['coolify']['api_token']
APP_UUID = "zkkw8wocws84gg4woc8kcoc4"
BASE = "https://coolify.titaniumlabs.us"

new_envs = [
    {"key": "ALPACA_API_KEY_C",    "value": "PKHF7ZBFCWID37426HCWNTZHNW"},
    {"key": "ALPACA_SECRET_KEY_C", "value": "Gd6ttG7g5w1MWy38Gs7VKY3R3GQT4LPCubTr6EowE2p5"},
]

for env in new_envs:
    data = json.dumps({
        "key": env["key"],
        "value": env["value"],
        "is_buildtime": False,
        "is_preview": False,
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/applications/{APP_UUID}/envs",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.load(r)
            print(f"Added {env['key']}: {resp}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Error adding {env['key']}: {e.code} {body[:200]}")
