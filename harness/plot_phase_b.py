# -*- coding: utf-8 -*-
"""Phase B v1 figures.

fig8 三联：
  (1) A 题命中误差 by 臂（写满 30 秒的达成度）
  (2) A 题各臂**写出的 token 数**——这是「模型真的拿速率给输出定量」的直接证据
  (3) B 题换算保真度：模型答的秒数 vs token÷给定速率（y=x 即完全照用）
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
from harness.analyze import bootstrap_ci  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

ARM_CN = {
    "base": "基线（无反馈）",
    "speed_cal": "注入标定 TPS",
    "speed_range": "注入 TPS+区间",
    "elapsed": "注入绝对秒数",
}
COLORS = {"base": "#7A8299", "speed_cal": "#3B82F6",
          "speed_range": "#8B5CF6", "elapsed": "#F59E0B"}
ARM_ORDER = ["base", "speed_cal", "speed_range", "elapsed"]


def med(xs):
    return st.median(xs) if xs else float("nan")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAW, "phase_b_30s.jsonl")
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    A, B = {}, {}
    for r in recs:
        if r["metrics"].get("error"):
            continue
        A.setdefault(r["arm"], {"hit": [], "tok": [], "gen": [], "dur": [], "trial": []}) \
            if r["phase"] == "B_A" else None
        if r["phase"] == "B_A":
            d = A.setdefault(r["arm"], {"hit": [], "tok": [], "gen": [], "dur": [], "trial": []})
            d["hit"].append(abs(r["metrics"]["gen_s"] - r["target_s"]) / r["target_s"])
            d["tok"].append(r["metrics"]["out_tokens"])
            d["gen"].append(r["metrics"]["gen_s"])
            d["dur"].append(r["metrics"]["duration_s"])
            d["trial"].append(r["trial"])
        else:
            B.setdefault(r["arm"], []).append(r)
    arms = [a for a in ARM_ORDER if a in A or a in B]

    # B 题里写进用户消息的速率（phase_b.py 标定时的中位）
    cal_rate = 76.5
    calp = os.path.join(OUT, "tps_analysis.json")
    if os.path.exists(calp):
        d = json.load(open(calp, encoding="utf-8"))
        vv = []
        for v in d.values():
            vv.extend(v.get("tps_text") or [])
        if vv:
            vv = sorted(vv)
            cal_rate = vv[len(vv) // 2]

    fig, axes = plt.subplots(1, 3, figsize=(17, 5.2))

    # ---- (1) hit error by arm
    ax = axes[0]
    vals, labs, errs, colors = [], [], [], []
    for arm in arms:
        he = A.get(arm, {}).get("hit", [])
        if not he:
            continue
        m = med(he)
        vals.append(m)
        labs.append(ARM_CN.get(arm, arm))
        colors.append(COLORS[arm])
        ci = bootstrap_ci(he) if len(he) >= 3 else (None, None)
        if ci[0] is not None:
            errs.append([max(0.0, m - ci[0]), max(0.0, ci[1] - m)])
        else:
            errs.append([0, 0])
    y = list(range(len(vals)))
    ax.barh(y, vals, xerr=[[e[0] for e in errs], [e[1] for e in errs]],
            color=colors, height=0.6, error_kw=dict(ecolor="#333", lw=1.1, capsize=4))
    for i, v in enumerate(vals):
        ax.text(v + 0.02, i, f"{v:.3f}", va="center", fontsize=9)
    ax.set_yticks(y)
    ax.set_yticklabels(labs, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("med |(实际生成耗时 − 30s) / 30s|   越低越好")
    ax.set_title("(1) A 题：写满 30 秒的命中误差", fontsize=11)
    ax.grid(axis="x", alpha=0.25)

    # ---- (2) output token count by arm
    ax = axes[1]
    for i, arm in enumerate(arms):
        toks = A.get(arm, {}).get("tok", [])
        if not toks:
            continue
        jitter = [i - 0.16 + 0.32 * ((k % 3) / 2) for k in range(len(toks))]
        ax.scatter(jitter, toks, s=42, alpha=0.75, color=COLORS[arm],
                   edgecolors="white", linewidths=0.7,
                   label=f"{ARM_CN[arm]}（中位 {med(toks):.0f}）")
        ax.plot([i - 0.3, i + 0.3], [med(toks), med(toks)], color="#222", lw=2)
    ax.set_xticks(range(len(arms)))
    ax.set_xticklabels([ARM_CN.get(a, a) for a in arms], fontsize=9)
    ax.set_ylabel("一次回复输出的 token 数")
    ax.set_title("(2) A 题：各臂写出的篇幅（速率→长度的换算证据）", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)

    # ---- (3) B task conversion fidelity
    ax = axes[2]
    xs, ys = [], []
    for arm in arms:
        rows = [r for r in B.get(arm, []) if r["parsed"].get("estimate_s")]
        if not rows:
            continue
        xs.extend([r["tokens"] / cal_rate for r in rows])
        ys.extend([r["parsed"]["estimate_s"] for r in rows])
    lim = [0, max(xs + ys) * 1.08 if xs else 60]
    ax.plot(lim, lim, ls="--", color="#C0392B", lw=1.6, label="y=x（完全照给定的速率换算）")
    ax.scatter(xs, ys, s=48, alpha=0.8, color="#3B82F6")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel(f"期望秒数 = token 数 ÷ {cal_rate:.1f} tok/s")
    ax.set_ylabel("模型回答的秒数")
    ax.set_title("(3) B 题：给定速率后的换算保真度", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    fig.suptitle("Phase B v1：注入速率对「写满 30 秒」的影响（每次实验清空上下文，全程串行）",
                 fontsize=13.5, y=1.03)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig8_phase_b.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote", os.path.join(OUT, "fig8_phase_b.png"))


if __name__ == "__main__":
    main()
