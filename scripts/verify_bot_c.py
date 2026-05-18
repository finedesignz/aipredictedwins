import urllib.request, json
req = urllib.request.Request(
    'https://paper-api.alpaca.markets/v2/account',
    headers={'APCA-API-KEY-ID': 'PKHF7ZBFCWID37426HCWNTZHNW', 'APCA-API-SECRET-KEY': 'Gd6ttG7g5w1MWy38Gs7VKY3R3GQT4LPCubTr6EowE2p5'}
)
with urllib.request.urlopen(req) as r:
    d = json.load(r)
print(f"Bot C: equity=${float(d['equity']):,.2f} status={d['status']} currency={d['currency']}")
