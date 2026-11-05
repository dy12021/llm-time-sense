# -*- coding: utf-8 -*-
"""第一轮 T2（写满 N 秒）按「目标秒数 × 臂」拆开。

要回答的问题：Phase B v1 里「注入标定 TPS」让命中误差**变好**
（0.754 → 0.482，p=0.032），而第一轮同一类任务里「注入 TPS」**变差**
（0.574 vs 0.423）。两者差在哪？

两个候选解释：
  A. **目标时长不同**：第一轮把 3/8/20 秒**混在一起**统计，短目标上
     「按速率放大篇幅」会把 3 秒写成 8 秒，命中误差被拉大。
  B. **注入的速率准不准**：第一轮注入的是模型**自己上一周期**的实测速率
     （噪声大、含思维链 token），Phase B 注入的是标定中位（≈真实值）。

本脚本把命中误差按目标秒数分层，顺便给出各臂实际写出的篇幅，
用来看是「写多了」还是「没瞄准」。
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness.analyze import spearman  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")

ARM_CN = {
    "base": "基线",
    "speed": "注入上周期 TPS",
    "speed_count": "注入 TPS+token数",
    "speed_cum": "注入累计 TPS",
    "elapsed": "注入绝对秒数",
}
ARM_ORDER = ["base", "speed", "speed_count", "speed_cum", "elapsed"]


def med(xs):
    return st.median(xs) if xs else float("nan")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAW, "records.jsonl")
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    t2 = [r for r in recs if r["task_id"].startswith("target")
          and not r["metrics"].get("error")]

    print("=" * 96)
    print("第一轮 T2（写满 N 秒）：命中误差按「目标秒数 × 臂」分层")
    print("=" * 96)
    print(f"{'目标':>5}{'臂':<18}{'n':>4}{'med|hit|':>10}{'中位gen_s':>11}"
          f"{'中位token':>11}{'中位TPS':>10}")
    for tgt in (3, 8, 20):
        for arm in ARM_ORDER:
            rows = [r for r in t2 if r["task_id"] == f"target{tgt}" and r["arm"] == arm]
            if not rows:
                continue
            h = [abs(r["metrics"]["gen_s"] - tgt) / tgt for r in rows]
            print(f"{tgt:>5}{ARM_CN[arm]:<18}{len(rows):>4}{med(h):>10.3f}"
                  f"{med([r['metrics']['gen_s'] for r in rows]):>11.2f}"
                  f"{med([r['metrics']['out_tokens'] for r in rows]):>11.0f}"
                  f"{med([r['metrics']['tps'] for r in rows]):>10.1f}")
        # 该目标下的基线
        base = [r for r in t2 if r["task_id"] == f"target{tgt}" and r["arm"] == "base"]
        if base:
            bh = med([abs(r["metrics"]["gen_s"] - tgt) / tgt for r in base])
            bt = med([r["metrics"]["out_tokens"] for r in base])
            print(f"{'':>5}{'→ 基线参照':<18}{len(base):>4}{bh:>10.3f}"
                  f"{med([r['metrics']['gen_s'] for r in base]):>11.2f}{bt:>11.0f}")
        print("-" * 96)

    print()
    print("合并三个目标（第一轮原始口径）：")
    for arm in ARM_ORDER:
        rows = [r for r in t2 if r["arm"] == arm]
        if not rows:
            continue
        h = []
        for r in rows:
            tgt = int(r["task_id"].replace("target", ""))
            h.append(abs(r["metrics"]["gen_s"] - tgt) / tgt)
        print(f"  {ARM_CN[arm]:<18} n={len(rows):>3} med|hit|={med(h):.3f}")

    print()
    print("=" * 96)
    print("目标响应度：模型会不会「照着目标秒数调节篇幅」？")
    print("=" * 96)
    print("  同一臂内，3/8/20 秒目标对应的实际生成时长（中位）。")
    print("  如果模型有「时长目标」的概念，这三个数应该单调上升。")
    print()
    print(f"{'臂':<18}{'3s目标':>10}{'8s目标':>10}{'20s目标':>10}{'倍差':>9}"
          f"{'与目标的相关':>14}")
    for arm in ARM_ORDER:
        gs = []
        for tgt in (3, 8, 20):
            rows = [r for r in t2 if r["task_id"] == f"target{tgt}" and r["arm"] == arm]
            gs.append(med([r["metrics"]["gen_s"] for r in rows]) if rows else float("nan"))
        xs, ys = [], []
        for tgt in (3, 8, 20):
            for r in t2:
                if r["task_id"] == f"target{tgt}" and r["arm"] == arm:
                    xs.append(tgt)
                    ys.append(r["metrics"]["gen_s"])
        rho = spearman(xs, ys)
        ratio = (max(gs) / min(gs)) if all(g == g for g in gs) and min(gs) > 0 else float("nan")
        print(f"{ARM_CN[arm]:<18}{gs[0]:>10.2f}{gs[1]:>10.2f}{gs[2]:>10.2f}"
              f"{ratio:>9.2f}{rho:>14.3f}")
    print("  「与目标的相关」= Spearman(目标秒数, 实际生成时长)，按臂内全部试验算。")
    print("  接近 0 = 输出长度与目标无关（模型没有『时长目标』的概念）。")

    # ---- 落盘 JSON，供报告生成器自动引用 ----
    out = {"stratified": {}, "responsiveness": {}, "pooled": {}}
    for tgt in (3, 8, 20):
        for arm in ARM_ORDER:
            rows = [r for r in t2 if r["task_id"] == f"target{tgt}" and r["arm"] == arm]
            if not rows:
                continue
            h = [abs(r["metrics"]["gen_s"] - tgt) / tgt for r in rows]
            out["stratified"].setdefault(str(tgt), {})[arm] = {
                "n": len(rows),
                "median_abs_hit_err": med(h),
                "median_gen_s": med([r["metrics"]["gen_s"] for r in rows]),
                "median_out_tokens": med([r["metrics"]["out_tokens"] for r in rows]),
            }
    for arm in ARM_ORDER:
        rows = [r for r in t2 if r["arm"] == arm]
        if not rows:
            continue
        h = [abs(r["metrics"]["gen_s"] - int(r["task_id"].replace("target", ""))) / tgt
             for r, tgt in ((r, int(r["task_id"].replace("target", ""))) for r in rows)]
        xs = [int(r["task_id"].replace("target", "")) for r in rows]
        ys = [r["metrics"]["gen_s"] for r in rows]
        out["pooled"][arm] = {"n": len(rows), "median_abs_hit_err": med(h)}
        out["responsiveness"][arm] = {
            "gen_s_by_target": {str(tgt): med([r["metrics"]["gen_s"] for r in t2
                                               if r["task_id"] == f"target{tgt}"
                                               and r["arm"] == arm])
                                for tgt in (3, 8, 20)},
            "spearman_target_vs_gen_s": spearman(xs, ys),
        }
    dst = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "out", "r1_t2_stratified.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nwrote {dst}")


if __name__ == "__main__":
    main()
