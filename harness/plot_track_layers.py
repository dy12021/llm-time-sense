# -*- coding: utf-8 -*-
"""fig10：快慢交替发生在请求层，不在时间层。

每条横线 = 一次请求内逐 5 秒窗口的速率序列。
如果交替在「时间层」，同一条线内部会出现台阶；
如果交替在「请求层」，每条线是**平的**，只是线与线之间差 ~2 倍。
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

sys.stdout.reconfigure(encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")
WIN = 5.0


def window_rates(rec):
    m = rec["metrics"]
    gaps = m.get("chunk_gaps") or []
    chars = m.get("chunk_chars") or []
    if len(gaps) < 3 or len(chars) != len(gaps) + 1:
        return []
    times, t = [0.0], 0.0
    for g in gaps:
        t += g
        times.append(t)
    out, i, n = [], 0, len(times)
    while i < n:
        j = i
        while j < n and times[j] - times[i] < WIN:
            j += 1
        if j < n and times[j] - times[i] >= WIN:
            dt = times[j] - times[i]
            ntok = sum(chars[i:j])
            if dt > 0 and ntok > 0:
                out.append((times[i] + dt / 2, ntok / dt))
            i = j
        else:
            break
    return out


def main():
    fig, axes = plt.subplots(1, 2, figsize=(15, 6.2))
    for ax, (fname, title) in zip(
            axes,
            [("tps_long_items.jsonl", "数据集 1：items（确定性长度，30 秒）"),
             ("tps_long.jsonl", "数据集 2：longform（长文，30 秒）")]):
        recs = [json.loads(l) for l in open(os.path.join(RAW, fname), encoding="utf-8")
                if l.strip()]
        rows = []
        for r in recs:
            m = r["metrics"]
            if m.get("finish_reason") == "length":
                continue
            wr = window_rates(r)
            if len(wr) >= 2:
                rows.append((r["rep"], wr))
        rows.sort(key=lambda x: -st.median([v for _, v in x[1]]))
        y = 0
        for rep, wr in rows:
            rates = [v for _, v in wr]
            ax.plot([t for t, _ in wr], [y] * len(wr), "-", lw=2,
                    color="#3B82F6", alpha=0.85)
            ax.scatter([t for t, _ in wr], [y] * len(wr), s=26,
                       color="#3B82F6", zorder=3)
            ax.text(-0.6, y, f"rep{rep}", ha="right", va="center", fontsize=8.5)
            ax.text(max(t for t, _ in wr) + 0.6, y,
                    f"{st.median(rates):.0f} tok/s", va="center", fontsize=8.5,
                    color="#C0392B")
            y += 1
        ax.set_yticks([])
        ax.set_xlabel("请求内经过的时间 (s)")
        ax.set_xlim(-2.2, max(40, max((t for _, wr in rows for t, _ in wr), default=40) + 6))
        ax.set_title(title, fontsize=11)
        ax.grid(axis="x", alpha=0.25)
        ax.invert_yaxis()
    fig.suptitle("每条横线 = 一次请求内的 5 秒窗口速率：线内平坦、线间差 ~2 倍\n"
                 "→ 交替发生在「请求之间」（请求级抽签），与单次请求持续多久无关",
                 fontsize=12.5, y=1.04)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig10_track_layer.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote", os.path.join(OUT, "fig10_track_layer.png"))


if __name__ == "__main__":
    main()
