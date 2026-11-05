# -*- coding: utf-8 -*-
"""快慢交替发生在哪一层？——请求层 vs 时间层（滑动窗口口径）。

要回答：把单次生成从 30 秒拉到 3 分钟，能不能消掉「快慢交替」？

判据（用 5 秒滑动窗口速率，抹掉块大小抖动）：
  - 若一次请求**内部**的窗口速率是平的（无切轨）→ 路由是**请求级粘性**，
    交替发生在「请求之间」→ 拉长单次请求只让「这一次的速率」更准，
    下一次请求照样可能被抽到另一条轨，**交替不会消失**；
  - 若请求**内部**就有台阶（切轨）→ 拉长单次请求会把两轨平均掉，
    测出的是**假平均值**。
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")
WIN = 5.0


def med(xs):
    return st.median(xs) if xs else float("nan")


def window_rates(rec):
    """返回 (窗口中心时刻, 窗口速率) 序列；速率 = 窗口内 token 数 / 窗口时长。"""
    m = rec["metrics"]
    times = m.get("chunk_times")
    chars = m.get("chunk_chars")
    if not times or not chars or len(times) != len(chars):
        # 没有存时间戳时退回用 gap 累积
        gaps = m.get("chunk_gaps") or []
        if not gaps:
            return []
        t = 0.0
        times = [0.0]
        for g in gaps:
            t += g
            times.append(t)
        chars = (m.get("chunk_chars") or [])[:len(times)]
        if len(chars) != len(times):
            return []
    out = []
    i = 0
    n = len(times)
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


def analyze(path, label):
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    print("=" * 96)
    print(f"{label}  ({os.path.basename(path)})")
    print("=" * 96)
    print(f"  {'rep':>5}{'截断':>6}{'窗口速率中位':>13}{'请求内极值比':>14}"
          f"{'请求内CV':>10}{'gap中位':>10}   5s 窗口速率序列")
    within_cv, run_med = [], []
    for r in recs:
        m = r["metrics"]
        wr = window_rates(r)
        if len(wr) < 3:
            continue
        rates = [x[1] for x in wr]
        mm = med(rates)
        lo, hi = min(rates), max(rates)
        cv = st.pstdev(rates) / mm if mm else float("nan")
        within_cv.append(cv)
        run_med.append(mm)
        trunc = "TRUNC" if m.get("finish_reason") == "length" else ""
        seq = " ".join(f"{v:5.0f}" for v in rates)
        print(f"  {r['rep']:>5}{trunc:>6}{mm:>13.1f}{hi/max(lo, 1e-9):>14.2f}"
              f"{cv:>10.3f}{m.get('gap_median', 0):>10.4f}   {seq}")
    if run_med:
        print()
        print(f"  请求内窗口速率 CV 中位 = {med(within_cv):.3f}"
              f"   （0 = 一条轨到底，越大 = 请求内切轨越频繁）")
        print(f"  请求间中位速率 极值比 = {max(run_med)/min(run_med):.2f}×"
              f"   （请求内离散 / 请求间离散 = "
              f"{med(within_cv)/(st.pstdev(run_med)/med(run_med)):.2f}）")
        print()
    return within_cv, run_med


def main():
    w1, b1 = analyze(os.path.join(RAW, "tps_long_items.jsonl"), "数据集 1：items（确定性长度）")
    w2, b2 = analyze(os.path.join(RAW, "tps_long.jsonl"), "数据集 2：longform（长文）")

    print("=" * 96)
    print("合并判定")
    print("=" * 96)
    allb = b1 + b2
    allw = w1 + w2
    out = {}
    if allb:
        bw_cv = st.pstdev(allb) / med(allb)
        print(f"  请求内窗口速率 CV 中位 = {med(allw):.3f}")
        print(f"  请求间中位速率 CV      = {bw_cv:.3f}   极值比 {max(allb)/min(allb):.2f}×")
        ratio = med(allw) / max(bw_cv, 1e-9)
        print(f"  比值 = {ratio:.2f}")
        if ratio < 0.5:
            print("  → 交替主要在**请求之间**（请求内基本一条轨到底）：")
            print("    **拉长单次请求到 3 分钟不会消除交替**，只会让「这一次的速率」测得更准；")
            print("    下一条请求仍可能被路由到另一条轨。")
            print("    正确做法：跨多次请求做滑动窗口累计平均 + 留区间。")
            verdict = "交替在请求层"
        else:
            print("  → 请求内也会切轨：拉长到 3 分钟会把两轨平均掉，")
            print("    测出的是**假平均值**（方差被抹平，风险没消失）。")
            print("    正确做法：把窗口拉长到能覆盖单轨的尺度再取中位，并同时报 p10–p90。")
            verdict = "请求内也会切轨"
        out = {
            "within_request_cv_median": med(allw),
            "between_request_cv": bw_cv,
            "between_request_extreme_ratio": max(allb) / min(allb),
            "ratio_within_over_between": ratio,
            "verdict": verdict,
            "items_within_cv_median": med(w1),
            "longform_within_cv_median": med(w2),
            "items_between_cv": (st.pstdev(b1) / med(b1)) if b1 else None,
            "longform_between_cv": (st.pstdev(b2) / med(b2)) if b2 else None,
            "items_run_medians": b1,
            "longform_run_medians": b2,
        }
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "track_layer.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nwrote {p}")


if __name__ == "__main__":
    main()
