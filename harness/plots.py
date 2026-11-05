# -*- coding: utf-8 -*-
"""Figures for the LLM time-sense experiment."""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import tasks as T  # noqa: E402

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
RAW = os.path.join(ROOT, "raw")

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

COLORS = {
    "base": "#7A8299",
    "speed": "#3B82F6",
    "speed_count": "#10B981",
    "elapsed": "#F59E0B",
    "speed_cum": "#8B5CF6",
}
ARM_CN = {
    "base": "基线（无反馈）",
    "speed": "TPS 速度",
    "speed_count": "TPS + token 数",
    "elapsed": "耗时（秒）",
    "speed_cum": "累计 TPS",
}


def _load(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def _pairs(recs, kind, question=None):
    out = defaultdict(list)
    for r in recs:
        if r["kind"] != kind or r["metrics"].get("error"):
            continue
        if question and r.get("question") != question:
            continue
        est = r["parsed"].get("estimate_s")
        act = r["metrics"]["duration_s"]
        if est is None or not act:
            continue
        out[r["arm"]].append((float(est), float(act)))
    return out


def fig_calibration(recs, tag, title, fname):
    """log-log scatter estimate vs actual with y=x, per arm."""
    data = _pairs(recs, "S1_report")
    data2 = _pairs(recs, "S3_task", "prev_duration")
    for k, v in data2.items():
        data[k].extend(v)
    fig, axes = plt.subplots(1, 4, figsize=(19, 4.8), sharex=True, sharey=True)
    allv = [v for vs in data.values() for pair in vs for v in pair]
    if not allv:
        plt.close(fig)
        return
    lo = max(0.5, min(allv) * 0.7)
    hi = max(allv) * 1.4
    for ax, arm in zip(axes, T.ARMS):
        pts = data.get(arm, [])
        if pts:
            xs = [p[1] for p in pts]
            ys = [p[0] for p in pts]
            ax.scatter(xs, ys, s=46, alpha=0.75, color=COLORS[arm], edgecolor="white", linewidth=0.6)
        ax.plot([lo, hi], [lo, hi], ls="--", lw=1.2, color="#C0392B", label="完美校准 y=x")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
        ax.set_title(f"{ARM_CN[arm]}  (n={len(pts)})", fontsize=11)
        ax.set_xlabel("实际耗时 (s)")
        ax.grid(alpha=0.25, which="both", lw=0.5)
    axes[0].set_ylabel("模型报告的耗时 (s)")
    axes[0].legend(loc="upper left", fontsize=8, framealpha=0.9)
    fig.suptitle(title, fontsize=13.5, y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, fname), dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig_metric_bars(recs, fname, title):
    """median |ln ratio| for the three estimation tasks, per arm, with bootstrap CI."""
    specs = [
        ("T1 报出上一条回复用时", None),
        ("T3 回答前预估本条耗时", "S1_estimate"),
        ("T4 会话已过秒数", "S3_task"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8))
    for ax, (label, kind) in zip(axes, specs):
        vals, labels, errs = [], [], []
        for arm in T.ARMS:
            if kind is None:
                d = _pairs(recs, "S1_report")
                d2 = _pairs(recs, "S3_task", "prev_duration")
                pts = d.get(arm, []) + d2.get(arm, [])
            elif kind == "S1_estimate":
                pts = _pairs(recs, "S1_estimate").get(arm, [])
            else:
                pts = []
                for r in recs:
                    if (r["kind"] == "S3_task" and r["question"] == "elapsed_since_start"
                            and r["arm"] == arm and not r["metrics"].get("error")):
                        est = r["parsed"].get("estimate_s")
                        act = r.get("session_elapsed_at_prompt_s")
                        if est is not None and act:
                            pts.append((float(est), float(act)))
            le = [abs(math.log(e / a)) for e, a in pts if e > 0 and a > 0]
            vals.append(float(np.median(le)) if le else 0)
            labels.append(ARM_CN[arm])
            if len(le) >= 3:
                from harness.analyze import bootstrap_ci
                ci = bootstrap_ci(le)
                errs.append([vals[-1] - ci[0], ci[1] - vals[-1]])
            else:
                errs.append([0, 0])
        y = np.arange(len(vals))
        e = np.array(errs).T
        ax.barh(y, vals, xerr=e, color=[COLORS[a] for a in T.ARMS], height=0.62,
                error_kw=dict(ecolor="#333", lw=1.1, capsize=4))
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=9.5)
        ax.invert_yaxis()
        ax.set_xlabel("median |ln(估计/实际)|   越低越好")
        ax.set_title(label, fontsize=11)
        ax.grid(axis="x", alpha=0.25)
    fig.suptitle(title, fontsize=13.5, y=1.03)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, fname), dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig_fixed_duration(recs, fname, title):
    rows = defaultdict(list)
    for r in recs:
        if r["kind"] == "S2_write" and not r["metrics"].get("error"):
            rows[r["arm"]].append((r["parsed"]["target_s"], r["metrics"]["gen_s"]))
    if not rows:
        return
    targets = sorted({t for v in rows.values() for t, _ in v})
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    # left: actual gen time vs target, per arm
    w = 0.8 / len(T.ARMS)
    for i, arm in enumerate(T.ARMS):
        xs, ys = [], []
        for t in targets:
            vals = [g for tt, g in rows.get(arm, []) if tt == t]
            xs.append(t + (i - 1.5) * w)
            ys.append(float(np.median(vals)) if vals else np.nan)
        axes[0].bar(xs, ys, width=w * 0.92, color=COLORS[arm], label=ARM_CN[arm])
    axes[0].plot(targets, targets, ls="--", color="#C0392B", lw=1.4, label="目标 y=x")
    axes[0].set_xlabel("目标时长 (s)")
    axes[0].set_ylabel("实际生成耗时 (s)")
    axes[0].set_title("固定时长：实际 vs 目标", fontsize=11)
    axes[0].legend(fontsize=8)
    axes[0].grid(axis="y", alpha=0.25)
    # right: relative hit error per target
    for arm in T.ARMS:
        xs, ys = [], []
        for t in targets:
            vals = [(g - t) / t for tt, g in rows.get(arm, []) if tt == t]
            xs.append(t)
            ys.append(float(np.median(vals)) if vals else np.nan)
        axes[1].plot(xs, ys, "o-", color=COLORS[arm], label=ARM_CN[arm], lw=1.8, ms=7)
    axes[1].axhline(0, color="#C0392B", ls="--", lw=1.3)
    axes[1].set_xlabel("目标时长 (s)")
    axes[1].set_ylabel("相对误差 (实际-目标)/目标")
    axes[1].set_title("固定时长：相对误差（0 = 命中）", fontsize=11)
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.25)
    fig.suptitle(title, fontsize=13.5, y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, fname), dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig_long_horizon(recs, fname, title):
    fig, ax = plt.subplots(figsize=(9, 5.4))
    any_pt = False
    for arm in T.ARMS:
        xs, ys = [], []
        by_cycle = defaultdict(list)
        for r in recs:
            if (r["kind"] == "S3_task" and r["question"] == "elapsed_since_start"
                    and r["arm"] == arm and not r["metrics"].get("error")):
                est = r["parsed"].get("estimate_s")
                act = r.get("session_elapsed_at_prompt_s")
                if est is not None and act:
                    by_cycle[r["cycle"]].append((float(est), float(act)))
        for cyc in sorted(by_cycle):
            vals = by_cycle[cyc]
            xs.append(cyc)
            ys.append(float(np.median([v[0] for v in vals])))
        if xs:
            any_pt = True
            ax.plot(xs, ys, "o-", color=COLORS[arm], label=ARM_CN[arm], lw=1.9, ms=6)
    # true elapsed reference: median over arms of actual
    actual_by_cycle = defaultdict(list)
    for r in recs:
        if (r["kind"] == "S3_task" and r["question"] == "elapsed_since_start"
                and not r["metrics"].get("error")):
            a = r.get("session_elapsed_at_prompt_s")
            if a:
                actual_by_cycle[r["cycle"]].append(a)
    ax.plot(sorted(actual_by_cycle), [float(np.median(actual_by_cycle[c])) for c in sorted(actual_by_cycle)],
            "k--", lw=2, label="真实已过秒数", alpha=0.75)
    if not any_pt:
        plt.close(fig)
        return
    ax.set_xlabel("会话轮次")
    ax.set_ylabel("估计的已过秒数 (s)")
    ax.set_title(title, fontsize=12.5)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, fname), dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig_runtime(recs, fname, title):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    tps = defaultdict(list)
    dur = defaultdict(list)
    for r in recs:
        if r["metrics"].get("error"):
            continue
        tps[r["arm"]].append(r["metrics"]["tps"])
        dur[r["arm"]].append(r["metrics"]["duration_s"])
    for arm in T.ARMS:
        if tps.get(arm):
            axes[0].scatter([arm] * len(tps[arm]), tps[arm], s=18, alpha=0.5, color=COLORS[arm])
            axes[1].scatter([arm] * len(dur[arm]), dur[arm], s=18, alpha=0.5, color=COLORS[arm])
    for ax, ylab, ttl in ((axes[0], "token/秒", "各臂实测吞吐 TPS"),
                          (axes[1], "秒", "各臂回复总耗时")):
        ax.set_ylabel(ylab)
        ax.set_title(ttl, fontsize=11)
        ax.grid(axis="y", alpha=0.25)
        ax.tick_params(axis="x", rotation=12)
    fig.suptitle(title, fontsize=13.5, y=1.03)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, fname), dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    os.makedirs(OUT, exist_ok=True)
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAW, "records.jsonl")
    recs = _load(path)
    print(f"loaded {len(recs)} records from {path}")
    fig_calibration(recs, "T1", "T1：模型报告的「上一条回复耗时」vs 真实耗时（对数坐标）",
                    "fig1_t1_calibration.png")
    fig_metric_bars(recs, "fig2_metric_bars.png",
                    "误差对比：三类时间估计任务的 median |ln(估计/实际)|（越低越好）")
    fig_fixed_duration(recs, "fig3_fixed_duration.png",
                       "T2：固定时长回复 —— 目标 vs 实际生成耗时")
    fig_long_horizon(recs, "fig4_long_horizon.png",
                     "T4：长期时间感 —— 会话已过秒数估计随轮次的漂移")
    fig_runtime(recs, "fig5_runtime.png", "运行时序特征：各臂实测吞吐与耗时分布")
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
