import urllib.request, json

req = urllib.request.Request(
    "https://coolify.titaniumlabs.us/api/v1/applications/zkkw8wocws84gg4woc8kcoc4/envs",
    headers={"Authorization": "Bearer 5|u8IdD5EsJ4PbogDT3fB6FiN2Mx5FeTwuuo0MnHfR0e89296b"}
)
with urllib.request.urlopen(req) as r:
    envs = json.loads(r.read())

for e in envs:
    k = e.get("key", "")
    if any(x in k for x in ("ALPACA", "DASH")):
        v = e.get("value") or ""
        print(f"{k} = {v[:12]}..." if v else f"{k} = (empty)")
