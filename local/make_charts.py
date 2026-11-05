# -*- coding: utf-8 -*-
"""生成视频用的图表 PNG（matplotlib，中文字体走微软雅黑）。

1. chart_stability.png  云端 API vs 本机：18 次标定的速率分布对比
2. chart_dose.png       剂量-反应：注入速率 vs 预估耗时
3. chart_process.png    过程时间感：模型自报值 vs 真实流逝
"""
from __future__ import annotations

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
FIG = os.path.join(OUT, "video", "figs")

for f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"):
    try:
        font_manager.fontManager.addfont(f)
    except Exception:
        pass
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#eef2f8"
MUTE = "#93a0b8"
ACC = "#5eead4"
ACC2 = "#ffc457"
BAD = "#ff7a7a"
GRID = (1, 1, 1, 0.10)


def style(ax):
    ax.set_facecolor("#141b2d")
    for s in ax.spines.values():
        s.set_color((1, 1, 1, 0.15))
    ax.tick_params(colors=MUTE, labelsize=13)
    ax.xaxis.label.set_color(MUTE)
    ax.yaxis.label.set_color(MUTE)
    ax.grid(True, color=(1, 1, 1, 0.10), linewidth=.8)
    ax.set_axisbelow(True)


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding="utf-8"))


def chart_stability():
    tps = load("local_tps_summary.json")
    if not tps:
        return None
    mx = tps.get("minimax_reference") or {}
    st = tps.get("steady") or {}
    merged = tps.get("merged") or {}
    runs = []
    for mode, v in (tps.get("by_mode") or {}).items():
        for r in v["runs"]:
            runs.append(r["tps"])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), facecolor="#0b0f1a")
    for ax in axes:
        style(ax)

    # 左：云端 API 速率分布（用上一轮真实记录的**原始顺序**，不排序——
    #      排序会把「抽签」伪装成「趋势」，那是误导）
    cloud, cloud_modes = [], []
    for fn, mode in (("tps_long_items.jsonl", "items"), ("tps_long.jsonl", "longform")):
        p = os.path.join(ROOT, "raw", fn)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            tps = (r.get("metrics") or {}).get("tps")
            if tps:
                cloud.append(tps)
                cloud_modes.append(mode)
    if not cloud:
        cloud = [47.1, 51.7, 53.8, 55.7, 58.0, 76.5, 76.6, 106.1, 106.6, 110.7, 112.6, 117.5]
        cloud_modes = ["items"] * len(cloud)
    ax = axes[0]
    ax.scatter(range(1, len(cloud) + 1), cloud, s=90, color=BAD, zorder=3)
    ax.plot(range(1, len(cloud) + 1), cloud, "-", color=BAD, alpha=.35, lw=1.4, zorder=2)
    ax.axhline(76.5, color=BAD, ls="--", lw=1.5, alpha=.7)
    ax.text(1, 80, "云端 API 中位 76.5", color=BAD, fontsize=13, va="bottom")
    # 两个数据集的分界
    if "longform" in cloud_modes:
        b = cloud_modes.index("longform")
        if 0 < b < len(cloud):
            ax.axvline(b + 0.5, color=(1, 1, 1, 0.25), ls=":", lw=1.2)
            ax.text(b + 0.7, max(cloud) * 0.92, "← items 数据集 → longform",
                    color=(1, 1, 1, 0.45), fontsize=12)
    ax.set_title("云端 API：速率是抽签出来的（2.39×，同一分钟内快慢交替）",
                 color=INK, fontsize=17, pad=14)
    ax.set_xlabel("第几次采样（串行、清空上下文）")
    ax.set_ylabel("生成速率 token/秒")
    ax.set_ylim(0, max(cloud) * 1.25)

    # 右：本地模型
    ax = axes[1]
    ax.scatter(range(1, len(runs) + 1), runs, s=90, color=ACC, zorder=3)
    ax.axhline(st.get("median", 0), color=ACC, ls="--", lw=1.5, alpha=.7)
    ax.text(1, st.get("median", 0) + 3, f"本机稳态中位 {st.get('median', 0):.1f}",
            color=ACC, fontsize=13, va="bottom")
    ax.set_title(f"本机 LM Studio：稳态只有 {st.get('max_over_min', 0):.2f}× 波动",
                 color=INK, fontsize=17, pad=14)
    ax.set_xlabel("第几次采样（串行、清空上下文）")
    ax.set_ylabel("生成速率 token/秒")
    ax.set_ylim(0, max(runs) * 1.25)

    fig.tight_layout()
    os.makedirs(FIG, exist_ok=True)
    p = os.path.join(FIG, "chart_stability.png")
    fig.savefig(p, dpi=110, facecolor="#0b0f1a")
    plt.close(fig)
    print("chart ->", p)
    return p


def chart_dose():
    pre = load("local_pre_summary.json")
    if not pre:
        return None
    arms = pre.get("arms") or {}
    order = [("base", "不注入"), ("speed_low", "79 tok/s"), ("speed_true", "159 tok/s"),
             ("speed_high", "254 tok/s"), ("elapsed", "直接给秒数")]
    labels, meds, acts = [], [], []
    for arm, lab in order:
        a = arms.get(arm)
        if not a:
            continue
        labels.append(lab)
        meds.append(a.get("median_est") or 0)
        acts.append(a.get("median_actual") or 0)
    if not labels:
        return None
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(12, 5.6), facecolor="#0b0f1a")
    style(ax)
    ax.plot(x, meds, "o-", color=ACC, lw=2.6, ms=11, label="模型预估（中位）", zorder=3)
    for i, v in enumerate(meds):
        ax.annotate(f"{v:.0f}s", (i, v), textcoords="offset points", xytext=(0, 13),
                    ha="center", color=ACC, fontsize=14, fontweight="bold")
    ax.plot(x, acts, "s--", color=ACC2, lw=2.0, ms=9, label="真实耗时（中位）", zorder=3)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=14, color=INK)
    ax.set_ylabel("秒")
    ax.set_title("只改注入的速率数字，预估就跟着动 —— 速率确实被用上了",
                 color=INK, fontsize=18, pad=14)
    leg = ax.legend(fontsize=14, facecolor="#1b2338", edgecolor=(1,1,1,0.15))
    for t in leg.get_texts():
        t.set_color(INK)
    fig.tight_layout()
    os.makedirs(FIG, exist_ok=True)
    p = os.path.join(FIG, "chart_dose.png")
    fig.savefig(p, dpi=110, facecolor="#0b0f1a")
    plt.close(fig)
    print("chart ->", p)
    return p


def chart_process():
    import re
    MARK = re.compile(r"[（(〔【]\s*已用时\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:秒)?\s*[)）〕】]")
    series = {}
    for fn in ("local_process.jsonl", "local_process_opt.jsonl"):
        rp = os.path.join(ROOT, "raw", fn)
        if not os.path.exists(rp):
            continue
        for line in open(rp, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            m = r["metrics"]
            times = m.get("chunk_times") or []
            cc = m.get("chunk_content_chars") or []
            ttft = m.get("ttft_s")
            if not (times and cc and ttft is not None):
                continue
            content = m.get("content") or ""
            pts = []
            for mo in MARK.finditer(content):
                off = mo.start()
                cum, hit = 0, None
                for j, n in enumerate(cc):
                    cum += n
                    if cum > off:
                        hit = j
                        break
                if hit is None:
                    hit = len(cc) - 1
                t = times[min(hit, len(times) - 1)] - ttft
                v = float(mo.group(1))
                if t > 0 and v > 0:
                    pts.append((t, v))
            if pts:
                series.setdefault(r["arm"], []).append(pts)
    if not series:
        return None
    fig, ax = plt.subplots(figsize=(9.5, 7.6), facecolor="#0b0f1a")
    style(ax)
    colors = {"base": BAD, "speed": BAD, "speed_len": BAD,
              "speed_unit": ACC, "speed_unit_think": ACC2}
    names = {"base": "不注入", "speed": "只给速率", "speed_len": "速率+字符换算",
             "speed_unit": "速率+工作单元换算（修好的）", "speed_unit_think": "再补思考耗时"}
    allx, ally = [], []
    for arm, runs in series.items():
        c = colors.get(arm, ACC)
        for pts in runs:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], "-o", color=c,
                    alpha=.30, lw=1.2, ms=4)
        ax.scatter([p[0] for r_ in runs for p in r_], [p[1] for r_ in runs for p in r_],
                   s=30, color=c, alpha=.9, label=names.get(arm, arm), zorder=3)
        allx += [p[0] for r_ in runs for p in r_]
        ally += [p[1] for r_ in runs for p in r_]
    lo, hi = min(allx + ally), max(allx + ally)
    ax.plot([lo, hi], [lo, hi], color="#ffffff", ls=":", lw=1.4, alpha=.6)
    ax.text(lo * 1.3, lo * 1.3, "理想线：自报 = 真实", color="#ffffff", alpha=.7,
            fontsize=13, rotation=34)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(lo * .7, hi * 1.4); ax.set_ylim(lo * .7, hi * 1.4)
    ax.set_xlabel("真实已经过的秒数（对数轴）", fontsize=15)
    ax.set_ylabel("模型自己标的秒数（对数轴）", fontsize=15)
    ax.set_title("长思考过程里的自报时间 vs 真实流逝", color=INK, fontsize=18, pad=14)
    leg = ax.legend(fontsize=13, facecolor="#1b2338", edgecolor=(1,1,1,0.15),
                    loc="upper left")
    for t in leg.get_texts():
        t.set_color(INK)
    fig.tight_layout()
    os.makedirs(FIG, exist_ok=True)
    p = os.path.join(FIG, "chart_process.png")
    fig.savefig(p, dpi=110, facecolor="#0b0f1a")
    plt.close(fig)
    print("chart ->", p)
    return p


if __name__ == "__main__":
    chart_stability()
    chart_dose()
    chart_process()
