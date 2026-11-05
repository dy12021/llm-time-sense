# -*- coding: utf-8 -*-
"""Phase B2 figures: dose-response of the injected rate.

fig9 三联：
  (1) A2 预估值 vs 注入速率  —— 预估值随速率下降 = 模型把速率当速率用了
  (2) A2 预估误差 by arm     —— 正确速率是否比基线更准
  (3) B2 隐含速率 vs 注入速率 —— 换算题里隐含速率是否跟着注入值走
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

ARM_ORDER = ["base", "speed_40", "speed_76", "speed_120", "elapsed"]
ARM_CN = {
    "base": "基线（无反馈）",
    "speed_40": "注入 40 tok/s",
    "speed_76": "注入 76 tok/s（实测标定）",
    "speed_120": "注入 120 tok/s",
    "elapsed": "注入真实实测耗时",
}
COLORS = {"base": "#7A8299", "speed_40": "#E4572E", "speed_76": "#3B82F6",
          "speed_120": "#17A398", "elapsed": "#F59E0B"}


def med(xs):
    return st.median(xs) if xs else None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAW, "phase_b2.jsonl")
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    ok = [r for r in recs if not r["metrics"].get("error")]

    A2, B2 = {}, {}
    for r in ok:
        m = r["metrics"]
        est = r["parsed"].get("estimate_s")
        if r["phase"] == "B2_A2":
            A2.setdefault(r["arm"], []).append({
                "rate": r.get("injected_rate"), "est": est,
                "actual": m["gen_s"], "trial": r["trial"],
                "err": (abs(__import__("math").log(est / m["gen_s"]))
                        if est and m["gen_s"] > 0 else None),
            })
        else:
            B2.setdefault(r["arm"], []).append({
                "tokens": r["tokens"], "rate": r.get("injected_rate"), "est": est,
                "implied": (r["tokens"] / est) if est else None,
            })

    fig, axes = plt.subplots(1, 3, figsize=(17, 5.2))

    # ---------- (1) A2: est vs injected rate ----------
    ax = axes[0]
    dose_arms = [a for a in ("speed_40", "speed_76", "speed_120") if A2.get(a)]
    for arm in dose_arms:
        rows = A2[arm]
        rate = rows[0]["rate"]
        ax.scatter([rate] * len(rows), [r["est"] for r in rows if r["est"]],
                   s=46, alpha=0.75, color=COLORS[arm], label=f"{ARM_CN[arm]} (n={len(rows)})")
        me = med([r["est"] for r in rows if r["est"]])
        if me is not None:
            ax.plot([rate, rate], [0, me], color=COLORS[arm], lw=1.2, ls=":", alpha=0.8)
            ax.plot([rate], [me], marker="_", ms=18, color=COLORS[arm], mew=2.4)
    acts = [r["actual"] for a in A2.values() for r in a]
    if acts:
        ax.axhspan(min(acts), max(acts), color="#C0392B", alpha=0.09,
                   label=f"实测生成时长范围 {min(acts):.0f}–{max(acts):.0f}s")
    ax.set_xlabel("注入的生成速度 (token/秒)")
    ax.set_ylabel("模型预估的生成耗时 (秒)")
    ax.set_title("(1) A2：预估值随注入速率移动吗？", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    # ---------- (2) A2: error by arm ----------
    ax = axes[1]
    labs, vals, errs, colors = [], [], [], []
    for arm in ARM_ORDER:
        rows = [r for r in A2.get(arm, []) if r["err"] is not None]
        if not rows:
            continue
        e = [r["err"] for r in rows]
        labs.append(ARM_CN[arm])
        vals.append(med(e))
        ci = bootstrap_ci(e) if len(e) >= 3 else (None, None)
        errs.append([vals[-1] - ci[0], ci[1] - vals[-1]] if ci[0] is not None else [0, 0])
        colors.append(COLORS[arm])
    y = list(range(len(vals)))
    ax.barh(y, vals, xerr=[[e[0] for e in errs], [e[1] for e in errs]],
            color=colors, height=0.6, error_kw=dict(ecolor="#333", lw=1.1, capsize=4))
    ax.set_yticks(y)
    ax.set_yticklabels(labs, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("med |ln(预估秒数 / 实测生成秒数)|   越低越好")
    ax.set_title("(2) A2：预估误差 by 臂", fontsize=11)
    ax.grid(axis="x", alpha=0.25)

    # ---------- (3) B2: implied rate vs injected rate ----------
    ax = axes[2]
    for arm in dose_arms:
        rows = [r for r in B2.get(arm, []) if r["implied"]]
        if not rows:
            continue
        rate = rows[0]["rate"]
        ax.scatter([rate] * len(rows), [r["implied"] for r in rows],
                   s=46, alpha=0.75, color=COLORS[arm], label=ARM_CN[arm])
        mi = med([r["implied"] for r in rows])
        ax.plot([rate], [mi], marker="_", ms=18, color=COLORS[arm], mew=2.4)
    base_imp = [r["implied"] for r in B2.get("base", []) if r["implied"]]
    if base_imp:
        ax.axhline(med(base_imp), color=COLORS["base"], ls="--", lw=1.5,
                   label=f"基线隐含速率 {med(base_imp):.0f} tok/s")
    lim = [0, 150]
    ax.plot(lim, lim, ls="--", color="#C0392B", lw=1.4, label="y=x（完全照注入值换算）")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel("注入的生成速度 (token/秒)")
    ax.set_ylabel("隐含速率 = token 数 ÷ 模型答的秒数")
    ax.set_title("(3) B2：换算题里隐含速率跟着注入值走吗？", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    fig.suptitle("Phase B2：注入速率的剂量-反应（30 秒自持实验，每次清空上下文，全程串行）",
                 fontsize=13.5, y=1.03)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig9_phase_b2_dose.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote", os.path.join(OUT, "fig9_phase_b2_dose.png"))


if __name__ == "__main__":
    main()
