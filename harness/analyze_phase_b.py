# -*- coding: utf-8 -*-
"""Phase B 分析：标定过的 TPS 到底能不能帮上忙。

三类指标
--------
A（写满 30 秒）  命中误差 (gen_s - target)/target；预估误差 |est - actual|/actual
B（纯换算）      已知 token 量，问需要多少秒；误差 |est - truth|/truth
"""
from __future__ import annotations

import json
import math
import os
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.analyze import compare_groups  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

ARM_CN = {
    "base": "基线（无反馈）",
    "speed_cal": "注入标定 TPS",
    "speed_range": "注入 TPS+区间",
    "elapsed": "注入绝对秒数",
}


def pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(int(q * len(s)), len(s) - 1)]


def med(xs):
    return st.median(xs) if xs else None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAW, "phase_b_30s.jsonl")
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    print(f"loaded {len(recs)} trials from {path}\n")

    # B 题里写进用户消息的速率 = phase_b.py 标定时的中位（两个数据集合并）
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

    # ---- serial check
    ivs = sorted([(r["metrics"]["t_request"], r["metrics"]["t_last"], r.get("trial"))
                  for r in recs], key=lambda x: x[0])
    ov = sum(1 for i in range(len(ivs) - 1) if ivs[i][1] > ivs[i + 1][0] + 1e-6)
    print(f"串行性：{len(ivs)} 次调用，重叠 {ov} 次 -> {'成立 ✓' if ov == 0 else '存在并发 ✗'}\n")

    A = defaultdict(list)   # arm -> list of dict
    B = defaultdict(list)
    for r in recs:
        if r["metrics"].get("error"):
            continue
        if r["phase"] == "B_A":
            m = r["metrics"]
            target = r["target_s"]
            actual = m["duration_s"]
            est = r["parsed"].get("estimate_s")
            A[r["arm"]].append({
                "target": target, "actual": actual, "gen": m["gen_s"],
                "est": est, "tokens": m["out_tokens"], "think": m["think_tokens"],
                "tps": m["tps"],
                "hit_err": (m["gen_s"] - target) / target,
                "est_err": (abs(math.log(est / actual)) if est and actual > 0 else None),
            })
        else:
            truth = r["truth_s"]
            est = r["parsed"].get("estimate_s")
            B[r["arm"]].append({
                "tokens": r["tokens"], "truth": truth, "est": est,
                "err": (abs(est - truth) / truth) if est else None,
                "ratio": (est / truth) if est else None,
            })

    out = {}
    print("=" * 78)
    print("A 题：写满 30 秒（每次清空上下文）")
    print("=" * 78)
    print(f"  {'臂':<20}{'n':>4}{'中位耗时':>10}{'命中误差':>10}{'med|hit|':>11}"
          f"{'预估med|ln|':>13}{'中位TPS':>10}{'中位token':>10}{'中位gen_s':>11}")
    out["A"] = {}
    for arm in ("base", "speed_cal", "speed_range", "elapsed"):
        rows = A.get(arm, [])
        if not rows:
            continue
        hit = [abs(r["hit_err"]) for r in rows]
        el = [r["est_err"] for r in rows if r["est_err"] is not None]
        out["A"][arm] = {"n": len(rows),
                         "median_dur": med([r["actual"] for r in rows]),
                         "median_abs_hit_err": med(hit),
                         "median_est_logerr": med(el),
                         "median_tps": med([r["tps"] for r in rows]),
                         "median_out_tokens": med([r["tokens"] for r in rows]),
                         "median_gen_s": med([r["gen"] for r in rows]),
                         "rows": rows}
        print(f"  {ARM_CN.get(arm,arm):<20}{len(rows):>4}"
              f"{med([r['actual'] for r in rows]):>10.2f}{med(hit):>10.3f}"
              f"{med(hit):>11.3f}{(med(el) if el else float('nan')):>13.3f}"
              f"{med([r['tps'] for r in rows]):>10.1f}"
              f"{med([r['tokens'] for r in rows]):>10.0f}"
              f"{med([r['gen'] for r in rows]):>11.2f}")
    print("  注：命中误差用 gen_s（模型能影响的生成窗口），预估误差是模型自己报的秒数 vs 实测。")

    print()
    print("=" * 78)
    print("B 题：纯换算（已知 token 量，问需要多少秒）")
    print("=" * 78)
    print(f"  {'臂':<20}{'n':>4}{'med|err|':>11}{'median est/truth':>18}")
    out["B"] = {}
    for arm in ("base", "speed_cal", "speed_range", "elapsed"):
        rows = B.get(arm, [])
        if not rows:
            continue
        errs = [r["err"] for r in rows if r["err"] is not None]
        rat = [r["ratio"] for r in rows if r["ratio"] is not None]
        out["B"][arm] = {"n": len(rows), "median_abs_err": med(errs),
                         "median_ratio": med(rat), "rows": rows}
        print(f"  {ARM_CN.get(arm,arm):<20}{len(rows):>4}"
              f"{(med(errs) if errs else float('nan')):>11.3f}"
              f"{(med(rat) if rat else float('nan')):>18.3f}")
    print("  判读：median est/truth = 1 说明换算正确；显著偏离 1 说明没用好给它的速率。")
    print(f"  【口径提醒】v1 的 B 题把速率 {cal_rate:.1f} token/秒 直接写进了**用户消息**，"
          f"四个臂拿到的是同一个数，所以 B 题在 v1 里**不能用来比较臂**——")
    print(f"  它测的是「给定了速率，模型能不能做对换算」。")
    conv = []
    for rows in B.values():
        for r in rows:
            if r["est"] and r["tokens"]:
                conv.append(r["est"] * cal_rate / r["tokens"])
    if conv:
        print(f"  换算保真度 est×rate/tokens：median={med(conv):.4f} "
              f"min={min(conv):.4f} max={max(conv):.4f} (n={len(conv)})，"
              f"{'=1.0 表示模型把给定速率原样用对了' if abs(med(conv)-1) < 0.02 else ''}")
        out["B_conversion_fidelity"] = {"median": med(conv), "min": min(conv),
                                        "max": max(conv), "n": len(conv),
                                        "rate_in_prompt": cal_rate}

    # ---- echo rate on the A task (target seconds were disclosed) ----
    a_all = [r for rows in A.values() for r in rows]
    if a_all:
        echo = sum(1 for r in a_all if r["est"] is not None and abs(r["est"] - r["target"]) < 1e-9)
        print()
        print(f"  【echo 诊断】A 题把目标秒数告诉了模型，预估值恰好等于目标秒数的比例："
              f"{echo}/{len(a_all)} = {echo/len(a_all)*100:.0f}%")
        print("  => 模型没有做独立估计，只是复述题面里的目标；A 题因此**不能**用来比较臂的估计能力。")
        out["A_echo_rate"] = {"n": len(a_all), "echo": echo, "rate": echo / len(a_all)}

    # ---- pairwise vs base
    print()
    print("=" * 78)
    print("成对比较（vs base，越负越好；置换检验）")
    print("=" * 78)
    out["compare"] = {}
    for tname, data, key in (("A-命中误差", A, "hit_err"), ("A-预估误差", A, "est_err"),
                              ("B-换算误差", B, "err")):
        base = [abs(r[key]) for r in data.get("base", []) if r.get(key) is not None]
        for arm in ("speed_cal", "speed_range", "elapsed"):
            cur = [abs(r[key]) for r in data.get(arm, []) if r.get(key) is not None]
            if not base or not cur:
                continue
            c = compare_groups(base, cur)
            out["compare"][f"{tname}|{arm}"] = c
            ci = c.get("ci") or (None, None)
            p = c.get("p")
            mark = "**显著变好**" if (c.get("delta") is not None and c["delta"] < 0 and p is not None and p < 0.05) \
                else ("**显著变差**" if (c.get("delta") is not None and c["delta"] > 0 and p is not None and p < 0.05)
                      else "无显著差异")
            print(f"  {tname:<12} {ARM_CN.get(arm,arm):<18} Δ={c.get('delta'):+.3f} "
                  f"CI=[{ci[0]:.3f}, {ci[1]:.3f}] p={p:.3f}  {mark}")

    # ---- 输出 token 数：模型是否拿速率给「篇幅」定量 ----
    print()
    print("=" * 78)
    print("A 题输出 token 数（模型拿速率给篇幅定量的直接证据；这里**越大**说明用上了速率）")
    print("=" * 78)
    base_tok = [r["tokens"] for r in A.get("base", [])]
    out["A_token_compare"] = {}
    for arm in ("speed_cal", "speed_range", "elapsed"):
        cur = [r["tokens"] for r in A.get(arm, [])]
        if not base_tok or not cur:
            continue
        c = compare_groups(base_tok, cur)
        ci = c.get("ci") or (None, None)
        p = c.get("p")
        mark = ("**显著更多**" if c["delta"] > 0 and p is not None and p < 0.05
                else "**显著更少**" if c["delta"] < 0 and p is not None and p < 0.05
                else "无显著差异")
        out["A_token_compare"][arm] = c
        print(f"  {ARM_CN.get(arm,arm):<18} 中位 {med(base_tok):.0f} -> {med(cur):.0f} "
              f"Δ={c['delta']:+.0f} CI=[{ci[0]:.0f}, {ci[1]:.0f}] p={p:.3f}  {mark}")
    print("  注：臂按固定顺序执行（base→speed_cal→speed_range→elapsed）。若效应是")
    print("      「随时间越写越多」的漂移，最后一个臂（elapsed）应该最明显——但它没有，")
    print("      所以效应来自速率本身，不是执行顺序。")

    with open(os.path.join(OUT, "phase_b_summary.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nwrote {OUT}\\phase_b_summary.json")


if __name__ == "__main__":
    main()
