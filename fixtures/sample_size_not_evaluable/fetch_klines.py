"""Fetch BTCUSDT 1w klines from Binance public API (no key) for 2019-01-01..2024-12-31 -> btcusdt_1w.csv"""
import json, urllib.request, csv
S=1546300800000  # 2019-01-01 UTC (Binance weeks open Monday; first bar >= S)
E=1735689599999  # 2024-12-31 23:59:59.999 UTC
rows=[]; t=S-7*86400000*80  # warmup 80 weeks so MA60 is defined at start
while t<E:
    u=f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1w&startTime={t}&endTime={E}&limit=1000"
    d=json.load(urllib.request.urlopen(u,timeout=20))
    if not d: break
    rows+=d; t=d[-1][0]+1
with open("btcusdt_1w.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["open_time_ms","close"])
    for r in rows: w.writerow([r[0],r[4]])
print(len(rows))
