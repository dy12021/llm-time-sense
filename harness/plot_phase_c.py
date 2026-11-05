# -*- coding: utf-8 -*-
"""fig11/fig12：过程时间感——模型在生成过程中的时间标注 vs 真实流逝。

(1) 标注值 vs 真实经过时间：每臂每轮一条折线（按标记位置）。
    理想情况是贴着 y=x；系统性偏离说明它是「外推」而不是「感知」。
(2) 末标注 / 真实总耗时：三个臂谁估得更准（1.0 = 准）。
(3) 段增量 ΔN vs 真实段增量 Δt：斜率 ≈1 才算真的在感知流逝；
    斜率 ≈0 说明标注和真实快慢无关（纯按字数/结构外推）。
(4) **每轮的「标量步长」× 真实总耗时**：模型把 12 个标注排成等差数列，
    步长是它一次性定好的。这张图直接回答：
    「模型心里那一段大概多久」会不会随真实快慢变化。
    横轴真实耗时、纵轴步长；若没有关系 → 步长是纯猜的。
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
from harness.analyze import spearman  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

ARM_CN = {"base": "基线（无反馈）", "speed": "注入实测速率", "elapsed": "注入真实实测耗时"}
COLORS = {"base": "#7A8299", "speed": "#3B82F6", "elapsed": "#F59E0B"}
ARM_ORDER = ["base", "speed", "elapsed"]


def med(xs):
    return st.median(xs) if xs else None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAW, "phase_c.jsonl")
    png = sys.argv[2] if len(sys.argv) > 2 else "fig11_phase_c_process.png"
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    ok = [r for r in recs if not r["metrics"].get("error")]

    from harness.analyze_phase_c import one_record
    rows = [one_record(r) for r in ok]
    usable = [r for r in rows if r.get("slope_t") is not None]

    fig, axes = plt.subplots(2, 2, figsize=(15.5, 11.0))

    # ---- (1) 标注值 vs 真实经过时间
    ax = axes[0][0]
    for arm in ARM_ORDER:
        for r in [x for x in usable if x["arm"] == arm]:
            ps = r["pairs"]
            ax.plot([p["t"] for p in ps], [p["v"] for p in ps], "-o", ms=3.5,
                    lw=1.1, alpha=0.45, color=COLORS[arm])
    lim = [0, max((p["t"] for r in usable for p in r["pairs"]), default=100) * 1.1]
    ax.plot(lim, lim, ls="--", color="#C0392B", lw=1.6, label="y=x（标注与真实同步）")
    for arm in ARM_ORDER:
        rs = [r for r in usable if r["arm"] == arm]
        if rs:
            ax.plot([], [], "-o", color=COLORS[arm], label=f"{ARM_CN[arm]} (n={len(rs)})")
    ax.set_xlim(lim)
    ax.set_ylim(0, max((p["v"] for r in usable for p in r["pairs"]), default=100) * 1.1)
    ax.set_xlabel("真实经过时间 (s)")
    ax.set_ylabel("模型标注的「已用时」(s)")
    ax.set_title("(1) 标注 vs 真实流逝：系统性偏高 = 外推而非感知", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    # ---- (2) 末标注 / 真实总耗时
    ax = axes[0][1]
    for i, arm in enumerate(ARM_ORDER):
        rs = [r for r in usable if r["arm"] == arm and r.get("last_ratio")]
        if not rs:
            continue
        vals = [r["last_ratio"] for r in rs]
        ax.scatter([i] * len(vals), vals, s=52, alpha=0.8, color=COLORS[arm],
                   edgecolors="white", linewidths=0.8)
        ax.plot([i - 0.25, i + 0.25], [med(vals), med(vals)], color="#222", lw=2)
        ax.text(i, max(vals) * 1.12, f"中位 {med(vals):.2f}×", ha="center", fontsize=9)
    ax.axhline(1.0, color="#C0392B", ls="--", lw=1.6, label="1.0 = 估得准")
    ax.set_yscale("log")
    ax.set_xticks(range(len(ARM_ORDER)))
    ax.set_xticklabels([ARM_CN[a] for a in ARM_ORDER], fontsize=9)
    ax.set_ylabel("末次标注 ÷ 真实总生成时长")
    ax.set_title("(2) 它认为这条回复花了多久", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)

    # ---- (3) 段增量 ΔN vs Δt
    ax = axes[1][0]
    for arm in ARM_ORDER:
        xs, ys = [], []
        for r in [x for x in usable if x["arm"] == arm]:
            ps = r["pairs"]
            for i in range(1, len(ps)):
                xs.append(ps[i]["t"] - ps[i - 1]["t"])
                ys.append(ps[i]["v"] - ps[i - 1]["v"])
        if xs:
            ax.scatter(xs, ys, s=34, alpha=0.75, color=COLORS[arm], label=ARM_CN[arm])
    dtx, dty = [], []
    for r in usable:
        ps = r["pairs"]
        for i in range(1, len(ps)):
            dtx.append(ps[i]["t"] - ps[i - 1]["t"])
            dty.append(ps[i]["v"] - ps[i - 1]["v"])
    if dtx:
        lim2 = [0, max(max(dtx), max(dty)) * 1.05]
        ax.plot(lim2, lim2, ls="--", color="#C0392B", lw=1.6, label="y=x（真的在感知流逝）")
        ax.text(0.03, 0.92, f"Spearman(Δt, ΔN) = {spearman(dtx, dty):+.3f}",
                transform=ax.transAxes, fontsize=10, color="#222")
    ax.set_xlabel("真实段耗时 Δt (s)")
    ax.set_ylabel("模型标注增量 ΔN (s)")
    ax.set_title("(3) 过程感知：标注增量跟得上真实快慢吗", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    # ---- (4) 每轮「步长」× 真实总耗时
    ax = axes[1][1]
    allg, alls = [], []
    for arm in ARM_ORDER:
        xs, ys = [], []
        for r in [x for x in usable if x["arm"] == arm]:
            ps = r["pairs"]
            if len(ps) < 3:
                continue
            steps = [ps[i]["v"] - ps[i - 1]["v"] for i in range(1, len(ps))]
            step = med(steps)
            xs.append(r["gen_s"])
            ys.append(step)
        if xs:
            ax.scatter(xs, ys, s=62, alpha=0.85, color=COLORS[arm],
                       edgecolors="white", linewidths=0.8, label=f"{ARM_CN[arm]} (n={len(xs)})")
            allg.extend(xs)
            alls.extend(ys)
    if len(allg) >= 4:
        sp = spearman(allg, alls)
        ax.text(0.03, 0.94, f"Spearman(真实耗时, 步长) = {sp:+.3f}",
                transform=ax.transAxes, fontsize=10, color="#222")
    ax.set_xlabel("该轮真实总生成时长 (s)")
    ax.set_ylabel("模型标注的等差步长 (s/节)")
    ax.set_title("(4) 它「心里」一节写多久：会随真实快慢变吗", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    spec = next((r.get("spec") for r in usable if r.get("spec")), None)
    if not spec:
        spec = "短规格" if "phase_c_long" not in path else "长规格"
    fig.suptitle(f"Phase C：生成过程中模型的时间标注（{spec}｜编号小节内联标记，"
                 "每次实验清空上下文，全程严格串行）", fontsize=13.5, y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out_png = os.path.join(OUT, png)
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out_png)


if __name__ == "__main__":
    main()
