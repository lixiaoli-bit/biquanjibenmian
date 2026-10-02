# -*- coding: utf-8 -*-
"""一键跑完：抓数据 → 回测 → 生成 dashboard"""
import subprocess, sys, os, webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ("抓取数据 · 主脚本",     "scripts/fetch_all.py"),
    ("抓取数据 · 扩展",       "scripts/fetch_extra.py"),
    ("回测 · 因子/策略",      "scripts/backtest.py"),
    ("回测 · 扩展指标",       "scripts/backtest_extra.py"),
    ("回测 · 统计严谨性 V3",  "scripts/backtest_v3.py"),
    ("生成 dashboard",        "scripts/build_dashboard.py"),
]

def run(script):
    path = os.path.join(BASE, script)
    print(f"\n===== 执行 {script} =====")
    r = subprocess.run([sys.executable, path], cwd=BASE)
    if r.returncode != 0:
        print(f"*** {script} 失败，退出码 {r.returncode} ***")
        sys.exit(1)

def main():
    for label, script in STEPS:
        print(f"\n>>> {label}")
        run(script)

    out = os.path.join(BASE, "output", "dashboard.html")
    print(f"\n===== 全部完成 =====")
    print(f"打开：{out}")
    webbrowser.open("file:///" + out.replace("\\", "/"))

if __name__ == "__main__":
    main()