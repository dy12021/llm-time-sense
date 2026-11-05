# -*- coding: utf-8 -*-
"""L1 标定分析：本地模型 TPS 到底稳不稳？和 MiniMax API 的 2.39× 对比。

口径与 harness/analyze_tps.py 保持一致：
  * 请求内：5 秒滑动窗口速率 → CV
  * 请求间：每轮整体速率 → CV、极值比
  * 交替在请求层还是时间层：用「请求内窗口速率 CV / 请求间 CV」比值判定

输出：out/local_tps_summary.json
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
WINDOW_S = 5.0


def cv(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = st.mean(xs)
    if m == 0:
        return None
    return st.pstdev(xs) / m


def window_rates(times, chars, window=WINDOW_S):
    """滑动窗口速率（字符/秒）。返回 (窗口中心时刻, 速率)。"""
    if not times or len(times) < 2:
        return []
    out = []
    t0 = times[0]
    i = 0
    cum = 0
    for j, t in enumerate(times):
        cum += chars[j]
        while times[i] < t - window:
            cum -= chars[i]
            i += 1
        dt = t - times[i]
        if dt >= max(window * 0.4, 0.5):
            out.append((t - t0, cum / dt))
    return out


def analyze_file(path: str, mode: str) -> dict:
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("mode") != mode:
                continue
            recs.append(r)
    if not recs:
        return {}

    per_run = []
    within_cvs = []
    for r in recs:
        m = r["metrics"]
        tps = m.get("tps") or 0.0
        times = m.get("chunk_times") or []
        chars = m.get("chunk_chars") or []
        wr = window_rates(times, chars)
        w_rates = [x[1] for x in wr]
        wcv = cv(w_rates)
        within_cvs.append(wcv)
        per_run.append({
            "rep": r.get("rep"), "mode": mode,
            "duration_s": m.get("duration_s"), "gen_s": m.get("gen_s"),
            "ttft_s": m.get("ttft_s"),
            "out_tokens": m.get("out_tokens"), "think_tokens": m.get("think_tokens"),
            "content_tokens": m.get("content_tokens"),
            "tps": tps, "tps_content": m.get("tps_out"),
            "within_cv": wcv,
            "n_windows": len(wr),
            "window_rate_min": min(w_rates) if w_rates else None,
            "window_rate_max": max(w_rates) if w_rates else None,
            "finish": m.get("finish_reason"),
        })

    tps_list = sorted(x["tps"] for x in per_run if x["tps"])
    n = len(tps_list)
    between_cv = cv(tps_list)
    ratio = tps_list[-1] / tps_list[0] if n and tps_list[0] else None
    within_med = st.median([x for x in within_cvs if x is not None]) if any(
        x is not None for x in within_cvs) else None
    content_tps = sorted(x["tps_content"] for x in per_run if x["tps_content"])

    return {
        "mode": mode,
        "n_runs": n,
        "tps": tps_list,
        "tps_median": st.median(tps_list) if n else None,
        "tps_p10": tps_list[int(0.10 * n)] if n else None,
        "tps_p90": tps_list[min(int(0.90 * n), n - 1)] if n else None,
        "tps_min": tps_list[0] if n else None,
        "tps_max": tps_list[-1] if n else None,
        "tps_max_over_min": ratio,
        "tps_between_cv": between_cv,
        "tps_within_cv_median": within_med,
        "within_over_between": (within_med / between_cv) if (within_med and between_cv) else None,
        "content_tps_median": st.median(content_tps) if content_tps else None,
        "runs": per_run,
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(RAW, "local_tps.jsonl")
    result = {}
    for mode in ("longform", "items"):
        a = analyze_file(path, mode)
        if a:
            result[mode] = a
    if not result:
        raise SystemExit(f"没有可分析的记录：{path}")

    all_tps = []
    for v in result.values():
        all_tps.extend(v["tps"])
    all_tps.sort()
    n = len(all_tps)

    # 冷/热分层：本地模型第 1 次请求要付 CUDA 图编译/权重换页的预热成本，
    # 之后才进入稳态。报告必须把「冷启动那次」和「热态」分开，否则稳定性结论会被污染。
    warm_tps = []
    cold_tps = []
    per_mode_warm = {}
    for mode, v in result.items():
        wm = sorted(r["tps"] for r in v["runs"] if r["rep"] != 1)
        per_mode_warm[mode] = {
            "n": len(wm), "median": st.median(wm) if wm else None,
            "min": wm[0] if wm else None, "max": wm[-1] if wm else None,
            "max_over_min": (wm[-1] / wm[0]) if wm and wm[0] else None,
            "between_cv": cv(wm),
        }
        for r in v["runs"]:
            (cold_tps if r["rep"] == 1 else warm_tps).append(r["tps"])
    warm_tps.sort()
    nw = len(warm_tps)
    # 稳态：模型加载后的前两次请求要付预热成本（CUDA 图编译 / 权重换页），
    # 之后才进入可部署的稳态区间。三层都报，不挑好看的那个。
    steady = sorted(r["tps"] for v in result.values() for r in v["runs"] if r["rep"] >= 3)
    ns = len(steady)

    summary = {
        "merged": {
            "n": n,
            "median": st.median(all_tps),
            "p10": all_tps[int(0.10 * n)],
            "p90": all_tps[min(int(0.90 * n), n - 1)],
            "min": all_tps[0], "max": all_tps[-1],
            "max_over_min": all_tps[-1] / all_tps[0],
            "between_cv": cv(all_tps),
        },
        "warm": {
            "n": nw,
            "median": st.median(warm_tps) if nw else None,
            "p10": warm_tps[int(0.10 * nw)] if nw else None,
            "p90": warm_tps[min(int(0.90 * nw), nw - 1)] if nw else None,
            "min": warm_tps[0] if nw else None,
            "max": warm_tps[-1] if nw else None,
            "max_over_min": (warm_tps[-1] / warm_tps[0]) if nw else None,
            "between_cv": cv(warm_tps),
            "cold_first_run_tps": cold_tps[0] if cold_tps else None,
            "warmup_factor": (cold_tps[0] / st.median(warm_tps)) if (cold_tps and nw) else None,
        },
        "steady": {
            "n": ns,
            "median": st.median(steady) if ns else None,
            "min": steady[0] if ns else None,
            "max": steady[-1] if ns else None,
            "max_over_min": (steady[-1] / steady[0]) if ns and steady[0] else None,
            "between_cv": cv(steady),
            "note": "排除加载后的前两次预热请求（rep1/rep2），对应可部署的稳态区间",
        },
        "by_mode": result,
        "per_mode_warm": per_mode_warm,
        "minimax_reference": {
            "source": "api.minimax.cn MiniMax-M3.1-Flash（上一轮 Phase A）",
            "median": 76.5, "p10": 51.7, "p90": 106.6,
            "min": 47.1, "max": 112.6, "max_over_min": 2.39,
            "between_cv": 0.920, "within_cv_median": 0.177,
        },
    }
    with open(os.path.join(OUT, "local_tps_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    m = summary["merged"]
    w = summary["warm"]
    print(f"本地 {m['n']} 次生成（全部）：TPS 中位 {m['median']:.1f}，p10–p90 {m['p10']:.1f}–{m['p90']:.1f}，"
          f"极值 {m['min']:.1f}–{m['max']:.1f}，max/min = {m['max_over_min']:.2f}×，"
          f"请求间 CV = {m['between_cv']:.3f}")
    print(f"热态（去掉第 1 次冷启动）n={w['n']}：TPS 中位 {w['median']:.1f}，"
          f"p10–p90 {w['p10']:.1f}–{w['p90']:.1f}，max/min = {w['max_over_min']:.2f}×，"
          f"请求间 CV = {w['between_cv']:.3f}（冷启动那次只有 {w['cold_first_run_tps']:.1f}）")
    s = summary["steady"]
    print(f"稳态（排除加载后前两次预热）n={s['n']}：TPS 中位 {s['median']:.1f}，"
          f"{s['min']:.1f}–{s['max']:.1f}，max/min = {s['max_over_min']:.2f}×，"
          f"请求间 CV = {s['between_cv']:.3f}")
    for mode, v in result.items():
        print(f"  [{mode}] n={v['n_runs']} 中位 {v['tps_median']:.1f} "
              f"max/min={v['tps_max_over_min']:.2f}× 请求间CV={v['tps_between_cv']:.3f} "
              f"请求内CV中位={v['tps_within_cv_median']} "
              f"比值={v['within_over_between']}")
    print("\n对照 MiniMax API：max/min = 2.39×，请求间 CV = 0.920，请求内 CV 中位 = 0.177")


if __name__ == "__main__":
    main()
