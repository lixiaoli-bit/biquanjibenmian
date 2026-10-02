# -*- coding: utf-8 -*-
"""
因为我想bnb也从2020年开始，所以bnb走币安通道，先保存这个原始数据
抓取全部历史数据 + 实时快照
数据源：
  1. OKX 现货日K：BTC-USDT / ETH-USDT（2020-01-01 至今，分页）
  2. alternative.me 恐惧贪婪指数 FGI（全量历史 2018 至今）
  3. DefiLlama 稳定币总市值（全量 2018 至今）
  4. OKX ticker 实时快照（主流币）
保存到 data/ 目录
"""
import os, json, time, csv, urllib.request

for k in list(os.environ):
    if "proxy" in k.lower():
        os.environ.pop(k)

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)

# def get_json(url, timeout=30):
#     req = urllib.request.Request(url, headers=UA)
#     with urllib.request.urlopen(req, timeout=timeout) as r:
#         return json.loads(r.read())
import requests
def get_json(url, timeout=30, retries=4):
    last_err = None
    for i in range(retries):
        try:
            resp = requests.get(url, headers=UA, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            wait = 2 * (i + 1)
            print(f"  [retry {i+1}/{retries}] {url} -> {e}, {wait}s 后重试")
            time.sleep(wait)
    raise last_err

def fetch_okx_klines(inst_id, start_ts_ms, bar="1D", max_requests=40):
    """从最新往旧翻页抓取 OKX 日K，直到早于 start_ts_ms"""
    rows = {}
    after = None
    for i in range(max_requests):
        url = f"https://www.okx.com/api/v5/market/history-candles?instId={inst_id}&bar={bar}&limit=300"
        if after:
            url += f"&after={after}"
        d = get_json(url)
        if d.get("code") != "0":
            print(f"  [warn] {inst_id} 请求{i} code={d.get('code')} msg={d.get('msg')}")
            break
        batch = d["data"]  # [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
        if not batch:
            break
        added = 0
        for row in batch:
            ts = int(row[0])
            if ts < start_ts_ms:
                continue
            rows[ts] = row
            added += 1
        oldest = min(int(r[0]) for r in batch)
        print(f"  {inst_id} 第{i+1}批: {len(batch)}根, 新增{added}, 最早 {time.strftime('%Y-%m-%d', time.gmtime(oldest/1000))}")
        if oldest <= start_ts_ms or added == 0:
            break
        after = oldest
        time.sleep(0.25)
    return rows

def save_csv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    print(f"  保存 {path}: {len(rows)} 行")

def main():
    print("=== 1. OKX 历史日K ===")
    start_ms = 1577836800000  # 2020-01-01 UTC
    for inst in ["BTC-USDT", "ETH-USDT", "BNB-USDT"]:
        rows = fetch_okx_klines(inst, start_ms)
        # 按时间升序，取 [ts, open, high, low, close, vol]
        ordered = sorted(rows.items())
        out = [[time.strftime("%Y-%m-%d", time.gmtime(ts/1000)), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for ts, r in ordered]
        save_csv(os.path.join(DATA, f"okx_{inst.replace('-','_')}_day.csv"),
                 ["date", "open", "high", "low", "close", "vol"], out)

    print("\n=== 2. 恐惧贪婪指数 FGI 全量 ===")
    fng = get_json("https://api.alternative.me/fng/?limit=0")
    fng_rows = [[d["timestamp"], d["value"], d.get("value_classification", "")] for d in fng["data"]]
    # 时间戳是秒
    fng_rows = [[time.strftime("%Y-%m-%d", time.gmtime(int(ts))), v, c] for ts, v, c in fng_rows]
    save_csv(os.path.join(DATA, "fng_history.csv"), ["date", "fng_value", "classification"], fng_rows)

    print("\n=== 3. DefiLlama 稳定币市值 ===")
    stbl = get_json("https://stablecoins.llama.fi/stablecoincharts/all")
    # list of {date(str秒), totalCirculatingUSD: {peggedUSD: ...}}
    stbl_rows = []
    for d in stbl:
        if "date" not in d:
            continue
        tc = d.get("totalCirculatingUSD")
        val = tc.get("peggedUSD", 0) if isinstance(tc, dict) else 0
        stbl_rows.append([time.strftime("%Y-%m-%d", time.gmtime(int(d["date"]))), val])
    save_csv(os.path.join(DATA, "stablecoin_mcap.csv"), ["date", "totalCirculatingUSD"], stbl_rows)

    print("\n=== 4. OKX 实时 ticker 快照 ===")
    insts = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT", "DOGE-USDT", "ADA-USDT", "TON-USDT"]
    tickers = {}
    for inst in insts:
        try:
            d = get_json(f"https://www.okx.com/api/v5/market/ticker?instId={inst}")
            if d.get("code") == "0" and d["data"]:
                t = d["data"][0]
                tickers[inst] = {
                    "last": float(t["last"]),
                    "open24h": float(t["open24h"]),
                    "high24h": float(t["high24h"]),
                    "low24h": float(t["low24h"]),
                    "vol24h": float(t["vol24h"]),
                    "ts": t["ts"],
                }
                chg = (tickers[inst]["last"] / tickers[inst]["open24h"] - 1) * 100 if tickers[inst]["open24h"] else 0
                print(f"  {inst}: {tickers[inst]['last']:.2f}  24h {chg:+.2f}%")
        except Exception as e:
            print(f"  {inst} 失败: {e}")
        time.sleep(0.15)

    # FGI 当前值
    try:
        fng_now = get_json("https://api.alternative.me/fng/?limit=1")["data"][0]
        tickers["__fng__"] = {"value": int(fng_now["value"]), "classification": fng_now["value_classification"], "ts": fng_now["timestamp"]}
        print(f"  FGI 当前: {fng_now['value']} ({fng_now['value_classification']})")
    except Exception as e:
        print(f"  FGI 失败: {e}")

    # 稳定币当前市值
    try:
        stbl_now = get_json("https://stablecoins.llama.fi/stablecoins")
        total_now = sum(p.get("circulating", {}).get("peggedUSD", 0) for p in stbl_now.get("peggedAssets", []))
        tickers["__stablecoin_total__"] = {"circulatingUSD": total_now, "ts": int(time.time())}
        print(f"  稳定币总市值: {total_now/1e9:.2f}B USD")
    except Exception as e:
        print(f"  稳定币当前失败: {e}")

    with open(os.path.join(DATA, "snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(tickers, f, indent=2, ensure_ascii=False)
    print(f"\n  快照保存: data/snapshot.json ({len(tickers)} 项)")

    print("\n=== 完成 ===")

if __name__ == "__main__":
    main()
