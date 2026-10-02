import requests
import pandas as pd

# ========== 1. 抓取 Binance XRP/USDT 日线数据 ==========
url = "https://api.binance.com/api/v3/klines"

start_ts = int(pd.Timestamp("2020-01-01").timestamp() * 1000)
# end_ts   = int(pd.Timestamp("2026-10-01 23:59:59").timestamp() * 1000)
# 假设今天是 2026-10-02,下面一行表示2026-10-01 23:59:59
end_ts = int((pd.Timestamp.utcnow().normalize() - pd.Timedelta(seconds=1)).timestamp() * 1000)

all_data = []
current = start_ts

while current < end_ts:
    params = {
        "symbol": "SOLUSDT",
        "interval": "1d",
        "startTime": current,
        "endTime": end_ts,
        "limit": 3600
    }
    resp = requests.get(url, params=params)
    data = resp.json()
    if not data:
        break
    all_data.extend(data)
    current = data[-1][0] + 86400000  # 下一天

# ========== 2. 整理为 DataFrame ==========
df = pd.DataFrame(all_data, columns=[
    "OpenTime", "Open", "High", "Low", "Close", "Volume",
    "CloseTime", "QuoteVolume", "Trades", "TakerBuyBase",
    "TakerBuyQuote", "Ignore"
])

# 日期列
df["date"] = pd.to_datetime(df["OpenTime"], unit="ms")

# 数值列转 float
for c in ["Open", "High", "Low", "Close", "Volume"]:
    df[c] = df[c].astype(float)

# 重命名列为目标格式
df = df.rename(columns={
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "vol"
})

# 只保留需要的列，并按日期排序
df = df[["date", "open", "high", "low", "close", "vol"]].sort_values("date").reset_index(drop=True)

# ========== 3. 保留小数位 ==========
for col in ["open", "high", "low", "close"]:
    df[col] = df[col].round(1)
df["vol"] = df["vol"].round(6)

# ========== 4. 保存 ==========
df.to_csv("okx_SOL_USDT_day.csv", index=False, encoding="utf-8-sig")

print(df.head())
print(df.tail())
print(f"共 {len(df)} 行")
print("✅ 已保存到 okx_SOL_USDT_day.csv")