# -*- coding: utf-8 -*-
"""测试 OKX / alternative.me / DefiLlama 数据源连通性
沙箱默认代理 127.0.0.1:62297 会拦截部分 API，先删除代理环境变量直连；
直连失败时可用备用代理 127.0.0.1:7892。
"""
import os, sys, json, time

# 删除沙箱默认代理（关键）
for k in list(os.environ):
    if "proxy" in k.lower():
        os.environ.pop(k)

import urllib.request

PROXY_7892 = "http://127.0.0.1:7892"

def fetch(url, use_proxy=False, timeout=25, headers=None):
    req_headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    if use_proxy:
        proxy_handler = urllib.request.ProxyHandler({"http": PROXY_7892, "https": PROXY_7892})
        opener = urllib.request.build_opener(proxy_handler)
    else:
        opener = urllib.request.build_opener()
    t0 = time.time()
    with opener.open(req, timeout=timeout) as resp:
        body = resp.read()
    return body, time.time() - t0

def test(name, url, parse, headers=None):
    for use_proxy in [False, True]:
        try:
            body, el = fetch(url, use_proxy=use_proxy, headers=headers)
            result = parse(body)
            print(f"[OK] {name} (proxy={use_proxy}) {el:.1f}s -> {result}")
            return
        except Exception as e:
            print(f"[FAIL] {name} (proxy={use_proxy}): {type(e).__name__}: {str(e)[:150]}")
    print(f"[X] {name} 全部失败")

# 1. OKX 现货日K
def parse_okx(body):
    d = json.loads(body)
    return f"code={d.get('code')} rows={len(d.get('data', []))} latest={d['data'][0][0] if d.get('data') else None}"

test("OKX BTC-USDT 日K", "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1D&limit=5", parse_okx)

# 2. OKX ticker（实时行情）
def parse_ticker(body):
    d = json.loads(body)
    row = d["data"][0]
    return f"last={row['last']} 24hVol={row.get('vol24h')} ts={row['ts']}"

test("OKX ticker BTC-USDT", "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT", parse_ticker)

# 3. alternative.me 恐惧贪婪指数
def parse_fng(body):
    d = json.loads(body)
    return f"rows={len(d.get('data', []))} latest={d['data'][0]['value'] if d.get('data') else None}"

test("Alternative.me FGI", "https://api.alternative.me/fng/?limit=10", parse_fng)

# 4. DefiLlama 稳定币总市值
def parse_llama(body):
    d = json.loads(body)
    return f"totalSeries={len(d.get('total', []))} stablecoins={list(d.keys())[:6]}"

test("DefiLlama stablecoincharts", "https://stablecoins.llama.fi/stablecoincharts/all", parse_llama)

# 5. DefiLlama 当前稳定币市值
def parse_llama2(body):
    d = json.loads(body)
    return f"total={d.get('total')} breakdown={len(d.get('peggedAssets', []))}"

test("DefiLlama stablecoins current", "https://stablecoins.llama.fi/stablecoins", parse_llama2)

# 6. CoinGecko 简单测试（备用）
def parse_cg(body):
    d = json.loads(body)
    return f"btc_usd={d.get('bitcoin', {}).get('usd')}"

test("CoinGecko simple price", "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,tether&vs_currencies=usd", parse_cg)

print("\n=== 全部测试完成 ===")
