# -*- coding: utf-8 -*-
"""扩展数据计算：全部使用公开标准公式，追加到 backtest_result.json 的 extra 字段
- 技术指标（RSI/MACD/布林带/ATR/年化波动率）——公开标准公式
- 散点联动数据（FGI vs 未来30日收益，月度采样）
- 月度收益热力图（BTC 2020-2026）
- 回撤水下曲线（策略+基准）
- 多币归一化走势（7币 2023起）
- 相关性矩阵（7币近1年日收益 Pearson）
- 币种详情（每币最近200天K线 + 指标快照）
- 年度收益 / 滚动波动率 / 资金费率（真实接口）
"""
import os, json
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "output")

def load_csv(name, date_col="date"):
    df = pd.read_csv(os.path.join(DATA, name), parse_dates=[date_col])
    df[date_col] = df[date_col].dt.strftime("%Y-%m-%d")
    return df.drop_duplicates(subset=[date_col]).set_index(date_col)

# ---------------- 技术指标（公开标准公式） ----------------
def rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0); loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/n, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    return 100 - 100 / (1 + rs)

def macd(close, fast=12, slow=26, sig=9):
    dif = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    dea = dif.ewm(span=sig, adjust=False).mean()
    return dif, dea, (dif - dea) * 2

def bollinger(close, n=20, k=2):
    ma = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return ma + k*sd, ma, ma - k*sd

def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def ann_vol(close, n=30):
    return close.pct_change().rolling(n).std() * np.sqrt(365) * 100

def monthly_returns(close):
    """每年每月收益热力图数据"""
    r = close.pct_change().dropna()
    r.index = pd.to_datetime(r.index)
    # 兼容 pandas 2.2+（"ME"）与旧版（"M"）
    freq = "ME" if tuple(int(x) for x in pd.__version__.split(".")[:2]) >= (2, 2) else "M"
    m = r.resample(freq).apply(lambda x: (1+x).prod() - 1)
    return {d.strftime("%Y-%m"): round(float(v*100), 2) for d, v in m.items() if not np.isnan(v)}

def drawdown(cum):
    cum = pd.Series(cum)
    return ((cum / cum.cummax() - 1) * 100).round(2).tolist()

# ---------------- 主流程 ----------------
btc = load_csv("okx_BTC_USDT_day.csv")
eth = load_csv("okx_ETH_USDT_day.csv")
fng = load_csv("fng_history.csv").sort_index()
stbl = load_csv("stablecoin_mcap.csv")
mcap = load_csv("btc_marketcap.csv")
funding = load_csv("btc_funding_day.csv")

df = pd.DataFrame({"close": btc["close"], "high": btc["high"], "low": btc["low"], "open": btc["open"]})
df["fng"] = fng["fng_value"].astype(float)
df["stable_ratio"] = stbl["totalCirculatingUSD"].astype(float) / mcap["value"].reindex(df.index).ffill() * 100
df["sma200"] = df["close"].rolling(200).mean()
df["btc_ma200"] = (df["close"] / df["sma200"] - 1) * 100
df["fwd30"] = df["close"].shift(-31) / df["close"].shift(-1) - 1

extra = {}

# 1. BTC 技术指标（近 360 天）
ind = df.tail(360).copy()
extra["btc_indicators"] = {
    "dates": ind.index.tolist(),
    "rsi14": [round(x, 2) if not np.isnan(x) else None for x in rsi(ind["close"]).values],
    "macd": [round(x, 2) if not np.isnan(x) else None for x in macd(ind["close"])[0].values],
    "macd_sig": [round(x, 2) if not np.isnan(x) else None for x in macd(ind["close"])[1].values],
    "macd_hist": [round(x, 2) if not np.isnan(x) else None for x in macd(ind["close"])[2].values],
    "boll_up": [round(x, 1) if not np.isnan(x) else None for x in bollinger(ind["close"])[0].values],
    "boll_mid": [round(x, 1) if not np.isnan(x) else None for x in bollinger(ind["close"])[1].values],
    "boll_low": [round(x, 1) if not np.isnan(x) else None for x in bollinger(ind["close"])[2].values],
    "atr14": [round(x, 1) if not np.isnan(x) else None for x in atr(ind).values],
    "vol30": [round(x, 1) if not np.isnan(x) else None for x in ann_vol(ind["close"]).values],
}

# 2. 散点联动数据：FGI vs 未来30日收益（月度采样 + 近4年）
RECENT = "2022-08-13"
rec = df.loc[df.index >= RECENT].dropna(subset=["fwd30"])
months = rec.index.str[:7]
last_of_month = pd.Series(rec.index).groupby(months).last()
sp = rec.loc[last_of_month.values]
extra["scatter"] = [{
    "date": d, "fgi": round(float(r["fng"]), 1), "fwd30": round(float(r["fwd30"]*100), 2),
    "ma200": round(float(r["btc_ma200"]), 1),
    "stable_ratio": round(float(r["stable_ratio"]), 2)
} for d, r in sp.iterrows()]
print("散点样本数:", len(extra["scatter"]))

# 3. 月度收益热力图（BTC 2020-2026）
mm = monthly_returns(df["close"])
extra["monthly_heatmap"] = mm
years = sorted(set(k[:4] for k in mm))
months_all = ["01","02","03","04","05","06","07","08","09","10","11","12"]
extra["heatmap_matrix"] = [[round(mm.get(f"{y}-{m}", 0), 2) for m in months_all] for y in years]
extra["heatmap_years"] = years
extra["heatmap_months"] = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]

# 4. 回撤水下曲线
result = json.load(open(os.path.join(OUT, "backtest_result.json"), encoding="utf-8"))
nav_rec = result["nav_recent"]
extra["dd_recent"] = {
    "dates": nav_rec["dates"],
    "strategy": drawdown(nav_rec["strategy"]),
    "benchmark": drawdown(nav_rec["benchmark"]),
}

# 5. 多币归一化走势（2023起）+ 相关性矩阵（近1年）
coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA"]
closes = {}
for c in coins:
    closes[c] = load_csv(f"okx_{c}_USDT_day.csv")["close"]
coin_df = pd.DataFrame(closes).dropna()
norm = (coin_df / coin_df.iloc[0] - 1) * 100
extra["coin_norm"] = {"dates": norm.index.tolist(), "coins": coins,
                      "series": {c: [round(v, 1) for v in norm[c].values] for c in coins}}
# 近 1 年日收益相关
ret1y = coin_df.tail(365).pct_change().dropna()
corr = ret1y.corr()
extra["corr_matrix"] = {"coins": coins,
                        "values": [[round(float(corr.loc[a, b]), 3) for b in coins] for a in coins]}
print("相关性矩阵样例:", extra["corr_matrix"]["values"][0])

# 6. 币种详情（每币最近 200 天 K 线 + 指标快照）
detail = {}
for c in coins:
    kdf = load_csv(f"okx_{c}_USDT_day.csv").tail(200)
    close = kdf["close"]
    last = float(close.iloc[-1])
    r = float(rsi(close).iloc[-1]); dif, dea, hist = macd(close)
    vol = float(ann_vol(close).iloc[-1])
    chg_30 = (last / float(close.iloc[-30]) - 1) * 100
    detail[c] = {
        "symbol": c,
        "kline": [[d, round(float(o), 6), round(float(h), 6), round(float(l), 6), round(float(cl), 6), round(float(v), 0)]
                  for d, o, h, l, cl, v in kdf.reset_index().values],
        "last": round(last, 4),
        "rsi14": round(r, 1) if not np.isnan(r) else None,
        "macd": round(float(dif.iloc[-1]), 2) if not np.isnan(dif.iloc[-1]) else None,
        "macd_sig": round(float(dea.iloc[-1]), 2) if not np.isnan(dea.iloc[-1]) else None,
        "vol30": round(vol, 1) if not np.isnan(vol) else None,
        "chg30": round(chg_30, 2),
        "sma50": round(float(close.rolling(50).mean().iloc[-1]), 2) if len(close) >= 50 else None,
        "sma200": round(float(close.rolling(200).mean().iloc[-1]), 2) if len(close) >= 200 else None,
    }
extra["coin_detail"] = detail
print("币种详情:", {c: detail[c]["last"] for c in coins})

# 7. 年度收益（BTC，当年首个→最后交易日，公开计算口径）
yd = df["close"].groupby(pd.to_datetime(df.index).year).agg(["first", "last"])
annual = {str(y): round((float(r["last"]) / float(r["first"]) - 1) * 100, 1) for y, r in yd.iterrows()}
extra["annual_returns"] = annual
print("年度收益:", annual)

# 8. 资金费率（真实接口，近90天）
extra["funding"] = {"dates": funding.index.tolist(),
                    "rates": [round(v, 4) for v in funding["funding_pct"].values]}
print("资金费率天数:", len(extra["funding"]["rates"]))

# 9. 实时衍生品/全局快照（直接透传）
snap = json.load(open(os.path.join(DATA, "snapshot.json"), encoding="utf-8"))
extra["live_extra"] = {k: v for k, v in snap.items() if k.startswith("__") and k not in ("__fng__", "__stablecoin_total__")}

result["extra"] = extra

def _clean(o):
    """递归清洗非 JSON 可序列化类型（Timestamp/np 类型兜底）"""
    if isinstance(o, dict): return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_clean(x) for x in o]
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, (np.bool_,)): return bool(o)
    if hasattr(o, "strftime"): return o.strftime("%Y-%m-%d")
    return o

with open(os.path.join(OUT, "backtest_result.json"), "w", encoding="utf-8") as f:
    json.dump(_clean(result), f, ensure_ascii=False, indent=1)
print("\n=== 扩展数据已合并到 backtest_result.json (extra 字段) ===")
