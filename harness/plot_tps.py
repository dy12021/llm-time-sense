# -*- coding: utf-8 -*-
"""Figures for the TPS calibration (Phase A).

fig6_rate_trace.png  每次 30 秒生成内的速率轨迹（滑动窗口）
fig7_overhead.png    时长 ~ token 数 的拆解：固定开销 + 本征速率
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness.analyze_tps import window_tps, linfit, pct  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def fig_rate_trace(recs, fname, title, win=5.0):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.2), sharey=True)
    n = len(recs)
    for i, r in enumerate(recs):
        for ax, which, color, label in ((axes[0], "all", "#3B82F6", "总吞吐"),
                                        (axes[1], "content", "#10B981", "正文吞吐")):
            ws = window_tps(r, win, which)
            if not ws:
                continue
            t = [w["t_start"] for w in ws]
            v = [w["tps"] for w in ws]
            ax.plot(t, v, lw=1.6, alpha=0.85, color=color,
                    label=f"rep{r['rep']} {label}")
    for ax, t in ((axes[0], "总吞吐（正文+思维链）"), (axes[1], "仅正文")):
        ax.set_xlabel("生成内时间 (s)")
        ax.set_title(t, fontsize=11)
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("滑动窗口 token/秒")
    axes[0].legend(fontsize=7, ncol=2)
    fig.suptitle(title, fontsize=13.5, y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, fname), dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig_overhead(recs, fname, title):
    prev = load(os.path.join(RAW, "records.jsonl"))
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # left: 30s runs — duration vs output tokens
    xs = [r["metrics"]["out_tokens"] for r in recs if not r["metrics"].get("error")]
    ys = [r["metrics"]["gen_s"] for r in recs if not r["metrics"].get("error")]
    axes[0].scatter(xs, ys, s=60, color="#3B82F6", zorder=3)
    for x, y, r in zip(xs, ys, recs):
        axes[0].annotate(f"r{r['rep']}", (x, y), fontsize=7,
                         textcoords="offset points", xytext=(4, 3))
    if xs:
        a = min(ys)
        b = (max(ys) - min(ys)) / max(max(xs) - min(xs), 1)
        axes[0].plot(sorted(xs), [a + b * (x - min(xs)) for x in sorted(xs)],
                     ls="--", color="#C0392B", lw=1.3, label="趋势线")
        axes[0].legend(fontsize=8)
    axes[0].set_xlabel("输出 token 数")
    axes[0].set_ylabel("生成耗时 gen_s (s)")
    axes[0].set_title("30 秒实验：同样 30 秒，吐出的 token 数差很多", fontsize=11)
    axes[0].grid(alpha=0.25)

    # right: 450-turn data, TPS vs output tokens (log-log) with the fitted curve
    px, py = [], []
    for r in prev:
        m = r["metrics"]
        if m.get("error") or m["out_tokens"] < 15:
            continue
        px.append(m["out_tokens"])
        py.append(m["out_tokens"] / max(m["gen_s"], 1e-6))
    fit = linfit([x for x in px], [0] * len(px)) if False else None
    xs2, ys2 = [], []
    for r in prev:
        m = r["metrics"]
        if m.get("error") or m["out_tokens"] < 15:
            continue
        xs2.append(m["out_tokens"])
        ys2.append(m["gen_s"])
    fit = linfit(xs2, ys2)
    axes[1].scatter(xs2, [x / y for x, y in zip(xs2, ys2)], s=9, alpha=0.45,
                    color="#7A8299", label="450 轮实验实测 TPS")
    if fit:
        a, b = fit["a"], fit["b"]
        grid = [20, 50, 100, 200, 500, 1000, 2000, 4000]
        axes[1].plot(grid, [x / (a + b * x) for x in grid], lw=2,
                     color="#C0392B", label=f"拟合: gen_s = {a:.3f} + {b:.5f}·tok")
        axes[1].axhline(1 / b, ls=":", color="#C0392B", lw=1.2,
                        label=f"本征速率上限 {1/b:.0f} token/s")
    axes[1].set_xscale("log")
    axes[1].set_yscale("log")
    axes[1].set_xlabel("输出 token 数")
    axes[1].set_ylabel("实测 TPS (token/秒)")
    axes[1].set_title("TPS 随输出长度的变化（450 轮实验）", fontsize=11)
    axes[1].legend(fontsize=7)
    axes[1].grid(alpha=0.25, which="both")
    fig.suptitle(title, fontsize=13.5, y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, fname), dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAW, "tps_long.jsonl")
    recs = load(path)
    print(f"loaded {len(recs)} records")
    fig_rate_trace(recs, "fig6_rate_trace.png",
                   "30 秒生成内的速率轨迹：5 秒滑动窗口（每次实验都清空上下文）")
    fig_overhead(recs, "fig7_overhead.png",
                 "TPS 拆解：固定开销 + 本征速率，以及输出长度对 TPS 的影响")
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
