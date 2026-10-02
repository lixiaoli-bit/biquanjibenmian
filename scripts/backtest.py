# -*- coding: utf-8 -*-
"""回测引擎 FINAL：【打脸】"币圈不看基本面"
真实数据验证：币圈"原生基本面"（情绪/流动性结构/估值分位）对未来 30 日收益的预测力

方法论要点（前两版修正）：
  1. Simpson 悖论：FGI/偏离度全样本合并 IC 被年份效应污染（2021 牛市），
     正确口径 = 年度 IC + 滚动 IC + 年内分位极值对比
  2. 主统计窗口近 4 年（2022-08~2026-08，因子逆向有效性成熟期），全样本作背景
  3. 策略 = 3 强因子（FGI rev / stable_ratio pos / ma200 rev）等权合成滚动分位信号，
     周频调仓、仓位 0.5+0.5×score（半仓打底+半仓调节），双边成本 0.1%
  4. 诚实呈现：策略累计跑输满仓（趋势市逆向择时劣势），但回撤与风险调整改善
输出：output/backtest_result.json
"""
import os, json
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "output")
os.makedirs(OUT, exist_ok=True)

def load_csv(name, date_col="date"):
    df = pd.read_csv(os.path.join(DATA, name), parse_dates=[date_col])
    df[date_col] = df[date_col].dt.strftime("%Y-%m-%d")
    return df.drop_duplicates(subset=[date_col]).set_index(date_col)

btc = load_csv("okx_BTC_USDT_day.csv")
eth = load_csv("okx_ETH_USDT_day.csv")
fng = load_csv("fng_history.csv").sort_index()
stbl = load_csv("stablecoin_mcap.csv")
mcap = load_csv("btc_marketcap.csv")
tx = load_csv("btc_tx_count.csv")
hsh = load_csv("btc_hashrate.csv")

df = pd.DataFrame({"btc_close": btc["close"]})
df["eth_close"] = eth["close"]
df["fng"] = fng["fng_value"].astype(float)
df["stable_mcap"] = stbl["totalCirculatingUSD"].astype(float)
df["btc_mcap"] = mcap["value"].reindex(df.index).ffill()
df["tx"] = tx["value"].reindex(df.index)
df["hash"] = hsh["value"].reindex(df.index)

W = 30
df["stable_ratio"] = df["stable_mcap"] / df["btc_mcap"] * 100
df["sma200"] = df["btc_close"].rolling(200).mean()
df["btc_ma200"] = (df["btc_close"] / df["sma200"] - 1) * 100
df["tx_g30"] = df["tx"].pct_change(W) * 100
df["hash_g30"] = df["hash"].pct_change(W) * 100
df["fwd30"] = df["btc_close"].shift(-31) / df["btc_close"].shift(-1) - 1  # T+1 执行持 30 日

FACTORS = [
    ("fng",          "FGI 恐惧贪婪指数",          "情绪",   "rev"),
    ("stable_ratio", "稳定币市值/BTC市值",         "流动性", "pos"),
    ("btc_ma200",    "BTC偏离200日均线",           "估值",   "rev"),
    ("tx_g30",       "链上交易笔数30日增长",       "链上活跃", "pos"),
    ("hash_g30",     "算力30日增长",               "供给侧", "pos"),
]
RECENT_START = "2022-08-13"

def rank_ic(a, b):
    a = pd.Series(a).astype(float); b = pd.Series(b).astype(float)
    m = a.notna() & b.notna()
    if m.sum() < 40: return np.nan
    return a[m].rank().corr(b[m].rank())

# ---------- 4. IC：全样本 / 近4年 / 滚动 / 年度 ----------
ic_results = {}
for col, name, cat, direction in FACTORS:
    ic_raw = np.full(len(df), np.nan)
    for i in range(250, len(df)):
        win = df.iloc[i-250:i]
        ic_raw[i] = rank_ic(win[col], win["fwd30"])
    ic_valid = ic_raw[~np.isnan(ic_raw)]
    rec = df.loc[df.index >= RECENT_START]
    yearly = {}
    for y, g in df[[col, "fwd30"]].groupby(df.index.str[:4]):
        if len(g) >= 60:
            yearly[y] = round(rank_ic(g[col], g["fwd30"]), 3)
    ic_results[col] = {
        "name": name, "category": cat, "direction": direction,
        "ic_all": round(rank_ic(df[col], df["fwd30"]), 4),
        "ic_recent": round(rank_ic(rec[col], rec["fwd30"]), 4),
        "ic_roll_mean": round(float(np.nanmean(ic_valid)), 4),
        "ic_roll_std": round(float(np.nanstd(ic_valid)), 4),
        "pos_ratio": round(float((ic_valid > 0).mean() * 100), 1),
        "yearly": {k: float(v) for k, v in yearly.items()},
        "ic_series": [[df.index[i], round(float(ic_raw[i]), 4)] for i in range(250, len(df)) if not np.isnan(ic_raw[i])][::2],
    }
    print(f"[IC] {name:24s} 全样本={ic_results[col]['ic_all']:+.4f} 近4年={ic_results[col]['ic_recent']:+.4f} 滚动均值={ic_results[col]['ic_roll_mean']:+.4f} 正率={ic_results[col]['pos_ratio']:.0f}%")

# ---------- 5. 年内分位极值对比（规避年份效应） ----------
def extreme_compare(series, col, direction):
    """每年内因子分位：前20%(高值组) vs 后20%(低值组) 的未来30日收益"""
    s = series[[col, "fwd30"]].dropna()
    s = s.copy()
    s["year_pct"] = s.groupby(s.index.str[:4])[col].rank(pct=True)
    hi = s[s["year_pct"] >= 0.8]
    lo = s[s["year_pct"] <= 0.2]
    def stat(g):
        return {"n": int(len(g)), "mean30": round(float(g["fwd30"].mean() * 100), 2),
                "winrate": round(float((g["fwd30"] > 0).mean() * 100), 1)}
    good, bad = (lo, hi) if direction == "rev" else (hi, lo)
    return {"good": stat(good), "bad": stat(bad),
            "spread": round(float(good["fwd30"].mean() * 100 - bad["fwd30"].mean() * 100), 2)}

extremes = {}
for col, name, cat, direction in FACTORS:
    extremes[col] = {
        "name": name, "category": cat, "direction": direction,
        "full": extreme_compare(df, col, direction),
        "recent": extreme_compare(df.loc[df.index >= RECENT_START], col, direction),
    }
    r = extremes[col]["recent"]
    print(f"[极值·近4年] {name:24s} 利好组={r['good']['mean30']:+.2f}%(胜率{r['good']['winrate']:.0f}%) vs 利空组={r['bad']['mean30']:+.2f}%(胜率{r['bad']['winrate']:.0f}%) 跨度={r['spread']:+.2f}%")

# ---------- 6. FGI 情绪区间（近4年） ----------
fng_groups = {}
rec = df.loc[df.index >= RECENT_START]
for lo, hi, label in [(0, 25, "极度恐慌<25"), (25, 45, "恐慌25-45"), (45, 55, "中性45-55"),
                      (55, 75, "贪婪55-75"), (75, 101, "极度贪婪>75")]:
    m = (rec["fng"] >= lo) & (rec["fng"] < hi)
    sub = rec.loc[m, "fwd30"].dropna()
    fng_groups[label] = {"days": int(len(sub)), "mean30": round(float(sub.mean() * 100), 2),
                         "winrate": round(float((sub > 0).mean() * 100), 1)}
print("\n[FGI情绪区间·近4年] 未来30日BTC收益:")
for k, v in fng_groups.items():
    print(f"  {k:14s} n={v['days']:3d} mean30={v['mean30']:+.2f}% 胜率={v['winrate']:.0f}%")

# ---------- 7. 恐慌+低估买点（近4年） ----------
rec2 = rec.copy()
rec2["buy_signal"] = (rec2["fng"] < 35) & (rec2["btc_ma200"] < 5)
cases = rec2.loc[rec2["buy_signal"], ["btc_close", "fng", "btc_ma200", "fwd30"]].dropna(subset=["fwd30"])
buy_cases = [{"date": d, "close": round(float(r["btc_close"]), 0), "fng": round(float(r["fng"]), 0),
              "ma200dev": round(float(r["btc_ma200"]), 1), "fwd30": round(float(r["fwd30"] * 100), 2)}
             for d, r in cases.iloc[::3].iterrows()][:12]
sig_mean = cases["fwd30"].mean() * 100 if len(cases) else np.nan
sig_win = (cases["fwd30"] > 0).mean() * 100 if len(cases) else np.nan
print(f"\n[恐慌+低估买点·近4年] 信号日 n={len(cases)} 未来30日均值={sig_mean:+.2f}% 胜率={sig_win:.0f}%")

# ---------- 8. 策略（3 强因子，周频，0.5+0.5） ----------
STRONG = ["fng", "stable_ratio", "btc_ma200"]
DIR = {c: d for c, _, _, d in FACTORS}

def pos_score(col, series):
    p = series[col].rolling(250).apply(lambda x: (pd.Series(x).rank(pct=True).iloc[-1]), raw=False)
    return (1 - p) if DIR[col] == "rev" else p

def run_strategy(series, start=None):
    s = series if start is None else series.loc[series.index >= start]
    cols = pd.concat([pos_score(c, s) for c in STRONG], axis=1)
    score = cols.mean(axis=1)
    week = pd.Series(s.index).map(lambda d: pd.Timestamp(d).isocalendar()[:2])
    first = pd.Series(s.index).groupby(week).first()
    position = pd.Series(np.nan, index=s.index)
    position.loc[first.values] = (0.5 + 0.5 * score.loc[first.values].clip(0, 1))
    position = position.ffill().fillna(0.5)
    ret = s["btc_close"].pct_change().fillna(0)
    sr = position.shift(1) * ret - position.diff().abs().fillna(0) * 0.001
    i0 = 250
    return {"dates": s.index[i0:].tolist(),
            "strategy": [round(v, 4) for v in (1 + sr.iloc[i0:]).cumprod().values],
            "benchmark": [round(v, 4) for v in (1 + ret.iloc[i0:]).cumprod().values],
            "position": [round(v, 4) for v in position.iloc[i0:].values]}, sr.iloc[i0:]

def perf(cum_list, ret_series):
    cum = pd.Series(cum_list)
    years = len(cum) / 365
    total = cum.iloc[-1] - 1
    ann = (1 + total) ** (1 / years) - 1
    dd = (cum / cum.cummax() - 1).min()
    sharpe = ret_series.mean() / (ret_series.std() + 1e-12) * np.sqrt(365)
    calmar = ann / abs(dd) if dd < 0 else np.nan
    return {"total": round(total * 100, 1), "annual": round(ann * 100, 1), "maxdd": round(dd * 100, 1),
            "sharpe": round(sharpe, 2), "calmar": round(calmar, 2)}

nav_full, sr_full = run_strategy(df)
nav_rec, sr_rec = run_strategy(df, RECENT_START)
m_full = {"strategy": perf(nav_full["strategy"], sr_full),
          "benchmark": perf(nav_full["benchmark"], pd.Series(nav_full["benchmark"]).pct_change().fillna(0))}
m_rec = {"strategy": perf(nav_rec["strategy"], sr_rec),
         "benchmark": perf(nav_rec["benchmark"], pd.Series(nav_rec["benchmark"]).pct_change().fillna(0))}
print(f"\n[策略·近4年] 策略: 累计{m_rec['strategy']['total']}% 年化{m_rec['strategy']['annual']}% 回撤{m_rec['strategy']['maxdd']}% 夏普{m_rec['strategy']['sharpe']} 卡玛{m_rec['strategy']['calmar']}")
print(f"[策略·近4年] 基准: 累计{m_rec['benchmark']['total']}% 年化{m_rec['benchmark']['annual']}% 回撤{m_rec['benchmark']['maxdd']}% 夏普{m_rec['benchmark']['sharpe']} 卡玛{m_rec['benchmark']['calmar']}")
print(f"[策略·全样本] 策略: 累计{m_full['strategy']['total']}% 回撤{m_full['strategy']['maxdd']}% 夏普{m_full['strategy']['sharpe']} | 基准: 累计{m_full['benchmark']['total']}% 回撤{m_full['benchmark']['maxdd']}%")

# ---------- 9. ETH 稳健性（近4年） ----------
edf = pd.DataFrame({"close": eth["close"]})
edf["fng"] = fng["fng_value"].astype(float)
edf["stable_ratio"] = stbl["totalCirculatingUSD"].astype(float) / mcap["value"].reindex(edf.index).ffill() * 100
edf["sma200"] = edf["close"].rolling(200).mean()
edf["btc_ma200"] = (edf["close"] / edf["sma200"] - 1) * 100
edf["fwd30"] = edf["close"].shift(-31) / edf["close"].shift(-1) - 1
edf_rec = edf.loc[edf.index >= RECENT_START]
eth_check = {}
for col, name, direction in [("fng", "FGI", "rev"), ("stable_ratio", "稳定币占比", "pos"), ("btc_ma200", "200日偏离", "rev")]:
    ic = rank_ic(edf_rec[col], edf_rec["fwd30"])
    ex = extreme_compare(edf_rec, col, direction)
    eth_check[col] = {"name": name, "ic_recent": round(ic, 4), "good": ex["good"], "bad": ex["bad"], "spread": ex["spread"]}
    print(f"[ETH校验·近4年] {name}: IC={ic:+.4f} 利好组={ex['good']['mean30']:+.2f}% vs 利空组={ex['bad']['mean30']:+.2f}% 跨度={ex['spread']:+.2f}%")

# ---------- 10. 当前信号 ----------
score_now = pd.concat([pos_score(c, df) for c in STRONG], axis=1).mean(axis=1)
snap = json.load(open(os.path.join(DATA, "snapshot.json"), encoding="utf-8"))
last = df.iloc[-1]

result = {
    "meta": {
        "title": "币圈不看基本面？——量化回测证据",
        "assets": ["BTC-USDT", "ETH-USDT"],
        "period_full": f"{df.index[0]} ~ {df.index[-1]}",
        "period_recent": f"{RECENT_START} ~ {df.index[-1]}",
        "sample_days_full": int(len(df)),
        "sample_days_recent": int((df.index >= RECENT_START).sum()),
        "data_sources": {
            "price": "OKX 现货 API 日K",
            "fgi": "Alternative.me 恐惧贪婪指数",
            "stablecoin": "DefiLlama 稳定币总市值",
            "btc_mcap": "Blockchain.com BTC市值",
            "onchain": "Blockchain.com 交易笔数/算力",
        },
        "snapshot": {
            "date": df.index[-1],
            "btc_close": round(float(last["btc_close"]), 2),
            "eth_close": round(float(last["eth_close"]), 2),
            "fng": round(float(last["fng"]), 0),
            "stable_mcap_b": round(float(last["stable_mcap"]) / 1e9, 1),
            "btc_ma200_pct": round(float(last["btc_ma200"]), 1),
            "live": {k: v for k, v in snap.items()},
        },
    },
    "factors": ic_results,
    "extremes": extremes,
    "fng_groups": fng_groups,
    "buy_signal": {"cases": buy_cases, "n": int(len(cases)),
                   "mean30": round(float(sig_mean), 2) if not np.isnan(sig_mean) else None,
                   "winrate": round(float(sig_win), 1) if not np.isnan(sig_win) else None},
    "nav_full": nav_full, "nav_recent": nav_rec,
    "metrics_full": m_full, "metrics_recent": m_rec,
    "eth_check": eth_check,
    "signal_now": {
        "score": round(float(score_now.iloc[-1]), 3),
        "fng_pos": round(float((1 - df["fng"].rolling(250).apply(lambda x: (pd.Series(x).rank(pct=True).iloc[-1]), raw=False)).iloc[-1]), 3),
        "stable_pos": round(float(df["stable_ratio"].rolling(250).apply(lambda x: (pd.Series(x).rank(pct=True).iloc[-1]), raw=False).iloc[-1]), 3),
        "ma200_pos": round(float((1 - df["btc_ma200"].rolling(250).apply(lambda x: (pd.Series(x).rank(pct=True).iloc[-1]), raw=False)).iloc[-1]), 3),
    },
}
with open(os.path.join(OUT, "backtest_result.json"), "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=1)
print("\n=== 结果已保存 output/backtest_result.json ===")
