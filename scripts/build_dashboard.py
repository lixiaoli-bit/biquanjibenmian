# -*- coding: utf-8 -*-
"""构建单文件 Dashboard：模板 + 回测JSON + K线数据 + 内嵌ECharts → output/dashboard.html
关键点（历史经验）：禁止全局 replace 占位符，用正则只替换对应 <script> 标签内的占位内容。
"""
import os, re, json, csv
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(BASE, "scripts", "template_dashboard.html")
DATA = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "output")
os.makedirs(OUT, exist_ok=True)

with open(TPL, encoding="utf-8") as f:
    html = f.read()

# 1. 回测 JSON
with open(os.path.join(OUT, "backtest_result.json"), encoding="utf-8") as f:
    result = json.load(f)

# 2. 追加 K 线（最近 200 天）+ FGI 近 200 天
btc_rows = list(csv.reader(open(os.path.join(DATA, "okx_BTC_USDT_day.csv"))))[1:]
kline = btc_rows[-200:]
result["kline"] = kline
result["kline_full"] = btc_rows  # 定投页用（全量 2000+ 天）

# 多币种全量数据（有多少币的数据就塞多少）
result["coins"] = {}
for sym in ["BTC", "BNB", "ETH", "SOL", "XRP", "DOGE", "ADA"]:#"XAU"这个没有1月1的数据，就算了
    path = os.path.join(DATA, f"okx_{sym}_USDT_day.csv")
    if os.path.exists(path):
        result["coins"][sym] = list(csv.reader(open(path)))[1:]
    else:
        result["coins"][sym] = []

fng_rows = list(csv.reader(open(os.path.join(DATA, "fng_history.csv"))))[1:]
fng_map = {r[0]: float(r[1]) for r in fng_rows}
fng90 = []
for r in kline:
    d = r[0]
    while d not in fng_map:
        d = (pd.Timestamp(d) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if d < "2018-02-01":
            break
    fng90.append(fng_map.get(d))
result["fng90"] = fng90

data_json = json.dumps(result, ensure_ascii=False, separators=(",", ":"))

# 3. 正则替换 embedded-data 标签内容（避免误伤 JS 代码中的占位符字符串）
html = re.sub(
    r'(<script id="embedded-data" type="application/json">)[\s\S]*?(</script>)',
    lambda m: m.group(1) + data_json + m.group(2),
    html, count=1,
)

# 4. 内嵌 ECharts 到 echarts-lib 标签
with open(os.path.join(BASE, "lib", "echarts.min.js"), encoding="utf-8") as f:
    echarts_js = f.read()
html = re.sub(
    r'(<script id="echarts-lib">)[\s\S]*?(</script>)',
    lambda m: m.group(1) + echarts_js + m.group(2),
    html, count=1,
)

out_path = os.path.join(OUT, "dashboard.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"dashboard.html 生成: {os.path.getsize(out_path)/1024:.0f} KB")
print("K线数据:", len(kline), "根 | FGI:", len(fng90), "天")
