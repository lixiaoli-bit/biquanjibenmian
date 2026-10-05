# -*- coding: utf-8 -*-
"""抓取扩展数据：7币日K（2023起）+ BTC资金费率历史 + 衍生品/全局快照"""
import os, json, time, csv, urllib.request

for k in list(os.environ):
    if "proxy" in k.lower():
        os.environ.pop(k)

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)

def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def fetch_okx_klines(inst_id, start_ts_ms, max_requests=30):
    rows = {}
    after = None
    for i in range(max_requests):
        url = f"https://www.okx.com/api/v5/market/history-candles?instId={inst_id}&bar=1D&limit=300"
        if after:
            url += f"&after={after}"
        try:
            d = get_json(url)
        except Exception as e:
            print(f"  {inst_id} 请求{i} 失败: {e}")
            break
        if d.get("code") != "0":
            break
        batch = d["data"]
        if not batch:
            break
        for row in batch:
            ts = int(row[0])
            if ts >= start_ts_ms:
                rows[ts] = row
        oldest = min(int(r[0]) for r in batch)
        if oldest <= start_ts_ms:
            break
        after = oldest
        time.sleep(0.2)
    out = [[time.strftime("%Y-%m-%d", time.gmtime(ts/1000)), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
           for ts, r in sorted(rows.items())]
    return out

def save_csv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(headers); w.writerows(rows)
    print(f"  保存 {os.path.basename(path)}: {len(rows)} 行")

def main():
    # 1. 新币日K（2023-01-01 起）。BTC/ETH 已有全量主文件（2020起），跳过避免覆盖
    start_ms = 1672531200000  # 2023-01-01
    insts = ["SOL-USDT", "XRP-USDT", "DOGE-USDT", "ADA-USDT"]
    print("=== 1. 新币日K (2023起) ===")
    for inst in insts:
        rows = fetch_okx_klines(inst, start_ms)
        save_csv(os.path.join(DATA, f"okx_{inst.replace('-','_')}_day.csv"), ["date","open","high","low","close","vol"], rows)

    # 2. BTC 资金费率历史（8h 一期，从 2023-01 翻页，用 after 取更早）
    print("\n=== 2. BTC 资金费率历史 ===")
    fund = {}
    after = None
    for i in range(40):
        url = "https://www.okx.com/api/v5/public/funding-rate-history?instId=BTC-USDT-SWAP&limit=100"
        if after:
            url += f"&after={after}"
        try:
            d = get_json(url)
        except Exception as e:
            print(f"  funding 第{i}批失败: {e}"); break
        batch = d.get("data", [])
        if not batch:
            print(f"  funding 第{i}批为空，结束"); break
        new = 0
        for r in batch:
            t = int(r["fundingTime"])
            if t >= start_ms:
                fund[t] = float(r["fundingRate"])
                new += 1
        b_min = min(int(r["fundingTime"]) for r in batch)
        print(f"  第{i+1}批 {len(batch)}条 新增{new} 最早 {time.strftime('%Y-%m-%d', time.gmtime(b_min/1000))}")
        if new == 0 or b_min <= start_ms:
            break
        after = str(b_min)
        time.sleep(0.2)
    # 按日聚合（每天取最后一次 funding）
    fund_day = {}
    for t, rate in sorted(fund.items()):
        fund_day[time.strftime("%Y-%m-%d", time.gmtime(t/1000))] = rate
    rows = [[d, r*100] for d, r in sorted(fund_day.items())]  # 百分比
    save_csv(os.path.join(DATA, "btc_funding_day.csv"), ["date", "funding_pct"], rows)

    # 3. 衍生品/全局快照
    print("\n=== 3. 实时快照扩展 ===")
    snap = json.load(open(os.path.join(DATA, "snapshot.json"), encoding="utf-8"))
    try:
        oi = get_json("https://www.okx.com/api/v5/public/open-interest?instId=BTC-USDT-SWAP")["data"][0]
        snap["__oi__"] = {"btc_oi_btc": float(oi["oiCcy"]), "btc_oi_usd": float(oi["oiUsd"]), "ts": oi["ts"]}
        print(f"  BTC OI: {float(oi['oiCcy']):.0f} BTC = {float(oi['oiUsd'])/1e9:.2f}B USD")
    except Exception as e:
        print(f"  OI 失败: {e}")
    try:
        oi_eth = get_json("https://www.okx.com/api/v5/public/open-interest?instId=ETH-USDT-SWAP")["data"][0]
        snap["__oi_eth__"] = {"eth_oi_eth": float(oi_eth["oiCcy"]), "eth_oi_usd": float(oi_eth["oiUsd"]), "ts": oi_eth["ts"]}
        print(f"  ETH OI: {float(oi_eth['oiCcy']):.0f} ETH = {float(oi_eth['oiUsd'])/1e9:.2f}B USD")
    except Exception as e:
        print(f"  ETH OI 失败: {e}")
    for inst, key in [("BTC-USDT", "__index_btc__"), ("ETH-USDT", "__index_eth__")]:
        try:
            idx = get_json(f"https://www.okx.com/api/v5/market/index-tickers?instId={inst}")["data"][0]
            last = snap[f"{inst}"]["last"]
            basis = (last / float(idx["idxPx"]) - 1) * 100
            snap[key] = {"idx": float(idx["idxPx"]), "basis_pct": round(basis, 4), "ts": idx["ts"]}
            print(f"  {inst} 指数 {float(idx['idxPx']):.1f} 基差 {basis:+.3f}%")
        except Exception as e:
            print(f"  index {inst} 失败: {e}")
    try:
        g = get_json("https://api.coingecko.com/api/v3/global")["data"]
        snap["__global__"] = {
            "total_mcap_usd": g["total_market_cap"]["usd"],
            "btc_dominance": g["market_cap_percentage"]["btc"],
            "eth_dominance": g["market_cap_percentage"]["eth"],
            "total_vol_usd": g["total_volume"]["usd"],
            "mcap_change_24h_pct": g["market_cap_change_percentage_24h_usd"],
            "ts": int(time.time())}
        print(f"  总市值 {g['total_market_cap']['usd']/1e12:.2f}T  BTC主导 {g['market_cap_percentage']['btc']:.1f}%")
    except Exception as e:
        print(f"  global 失败: {e}")
    try:
        st = get_json("https://stablecoins.llama.fi/stablecoins")
        pegged = {}
        for p in st.get("peggedAssets", []):
            sym = p.get("symbol", "")
            if sym in ("USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDe", "PYUSD"):
                circ = p.get("circulating", {}).get("peggedUSD", 0)
                pegged[sym] = round(circ, 0)
        snap["__stablecoin_breakdown__"] = {"ts": int(time.time()), "items": pegged}
        print(f"  稳定币构成: {pegged}")
    except Exception as e:
        print(f"  稳定币构成失败: {e}")

    with open(os.path.join(DATA, "snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    print(f"\n快照已更新: {len(snap)} 项")
    print("=== 完成 ===")

if __name__ == "__main__":
    main()
