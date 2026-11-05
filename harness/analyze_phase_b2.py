# -*- coding: utf-8 -*-
"""Phase B2 分析：注入速率到底有没有变成「时间感」。

三个判据
--------
1. **剂量-反应**（核心）：同一任务、同一措辞，只改注入的速率数字。
   - A2 题：预估值随注入速率单调下降 => 速率被用起来了。
     拟合 ln(est) = a + b·ln(rate)：b=0 表示完全没用；b=-1 表示完全当速率用
     （est = 自身估的 token 数 ÷ rate）。
   - B2 题：隐含速率 = tokens / 模型答的秒数。若模型用了注入的速率，
     隐含速率会随注入速率同向移动。
2. **增益**：正确速率（实测标定中位）下，预估误差是否比基线更小。
   A2 主指标 = med|ln(est / 实测生成时长)|。
3. **对照**：elapsed 臂（注入真实实测耗时）是否比 base 好——绝对时间量是不是
   真的更有用。
"""
from __future__ import annotations

import json
import math
import os
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.analyze import compare_groups, spearman  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

ARM_ORDER = ["base", "speed_40", "speed_76", "speed_120", "elapsed"]
ARM_CN = {
    "base": "基线（无反馈）",
    "speed_40": "注入 40 tok/s（反事实剂量）",
    "speed_76": "注入 76 tok/s（实测标定）",
    "speed_120": "注入 120 tok/s（反事实剂量）",
    "elapsed": "注入真实实测耗时",
}
DOSE_ARMS = ["speed_40", "speed_76", "speed_120"]


def med(xs):
    return st.median(xs) if xs else None


def lsq_slope(xs, ys):
    """最小二乘斜率 y = a + b·x；不足 3 点返回 None。"""
    if len(xs) < 3:
        return None
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAW, "phase_b2.jsonl")
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    ok = [r for r in recs if not r["metrics"].get("error")]
    print(f"载入 {len(recs)} 条（无错误 {len(ok)} 条）自 {path}\n")

    # ---------------- 串行性 ----------------
    ivs = sorted((r["metrics"]["t_request"], r["metrics"]["t_last"]) for r in recs)
    ov = sum(1 for i in range(len(ivs) - 1) if ivs[i][1] > ivs[i + 1][0] + 1e-6)
    gaps = [ivs[i + 1][0] - ivs[i][1] for i in range(len(ivs) - 1)]
    print(f"串行性：{len(ivs)} 次调用，重叠 {ov} 次 "
          f"-> {'成立 ✓' if ov == 0 else '存在并发 ✗'}；"
          f"相邻间隔 min={min(gaps)*1000:.2f}ms median={med(gaps)*1000:.2f}ms" if gaps else "")
    print()

    out = {"serial": {"n": len(ivs), "overlaps": ov,
                      "min_gap_s": min(gaps) if gaps else None,
                      "median_gap_s": med(gaps)}}

    A2 = defaultdict(list)
    B2 = defaultdict(list)
    for r in ok:
        m = r["metrics"]
        est = r["parsed"].get("estimate_s")
        if r["phase"] == "B2_A2":
            actual = m["gen_s"]
            A2[r["arm"]].append({
                "trial": r["trial"], "topic": r["topic"],
                "rate": r.get("injected_rate"),
                "elapsed_hint": r.get("injected_elapsed_s"),
                "est": est, "actual_gen_s": actual, "actual_dur_s": m["duration_s"],
                "content_tokens": m["content_tokens"],
                "think_tokens": m["think_tokens"],
                "out_tokens": m["out_tokens"],
                "actual_rate": (m["content_tokens"] / actual) if actual > 0 else None,
                "err": (abs(math.log(est / actual)) if est and est > 0 and actual > 0 else None),
                "echoes_item_count": bool(r["parsed"].get("echoes_item_count")),
                "think_share": (m["think_tokens"] / m["out_tokens"]) if m["out_tokens"] else None,
            })
        else:
            B2[r["arm"]].append({
                "tokens": r["tokens"], "rate": r.get("injected_rate"), "est": est,
                "implied_rate": (r["tokens"] / est) if est else None,
                "gen_s": m["gen_s"],
            })

    # ================= A2 =================
    print("=" * 92)
    print("A2 题：自持 30 秒（不告知目标秒数，模型独立预估自己的生成耗时）")
    print("=" * 92)
    print(f"  {'臂':<26}{'n':>3}{'实测生成中位':>12}{'预估中位':>10}"
          f"{'med|ln(est/act)|':>17}{'隐含token中位':>14}{'实际token中位':>14}{'echo数':>8}")
    out["A2"] = {}
    for arm in ARM_ORDER:
        rows = A2.get(arm, [])
        if not rows:
            continue
        errs = [r["err"] for r in rows if r["err"] is not None]
        ests = [r["est"] for r in rows if r["est"]]
        implied_tok = [(r["est"] * r["rate"]) for r in rows
                       if r["est"] and r["rate"]]   # est × 注入速率 = 模型以为的 token 数
        echo = sum(1 for r in rows if r["echoes_item_count"])
        ratio = [r["est"] / r["actual_gen_s"] for r in rows
                 if r["est"] and r["actual_gen_s"] > 0]
        out["A2"][arm] = {
            "n": len(rows),
            "median_actual_gen_s": med([r["actual_gen_s"] for r in rows]),
            "median_est_s": med(ests),
            "median_abs_log_err": med(errs),
            "median_est_over_actual": med(ratio),
            "median_implied_tokens": med(implied_tok),
            "median_content_tokens": med([r["content_tokens"] for r in rows]),
            "median_actual_rate": med([r["actual_rate"] for r in rows if r["actual_rate"]]),
            "echo_item_count": echo,
            "rows": rows,
        }
        print(f"  {ARM_CN[arm]:<26}{len(rows):>3}"
              f"{med([r['actual_gen_s'] for r in rows]):>12.2f}"
              f"{med(ests):>10.1f}"
              f"{(med(errs) if errs else float('nan')):>17.3f}"
              f"{(med(implied_tok) if implied_tok else float('nan')):>14.0f}"
              f"{med([r['content_tokens'] for r in rows]):>14.0f}"
              f"{echo:>8}")
    print("  隐含token = 预估秒数 × 注入速率 = 模型‘以为’自己要写多少 token。")
    print("  echo数 = 预估秒数恰好等于条目数(133)的次数（抄题检查）。")
    print()
    print(f"  {'臂':<26}{'est/实测 中位':>16}{'est/实测 p10–p90':>20}")
    for arm in ARM_ORDER:
        rows = A2.get(arm, [])
        if not rows:
            continue
        ratio = sorted([r["est"] / r["actual_gen_s"] for r in rows
                        if r["est"] and r["actual_gen_s"] > 0])
        if not ratio:
            continue
        lo = ratio[max(0, int(0.1 * len(ratio)) - 1)]
        hi = ratio[min(int(0.9 * len(ratio)), len(ratio) - 1)]
        print(f"  {ARM_CN[arm]:<26}{med(ratio):>16.2f}{f'{lo:.2f}–{hi:.2f}':>20}")
    print("  est/实测 = 1 表示估得准；>1 表示高估。<1 表示低估。")

    # ---- A2 剂量-反应 ----
    print()
    print("-" * 92)
    print("A2 剂量-反应：预估值是否随注入速率移动？")
    print("-" * 92)
    doses = []
    for arm in DOSE_ARMS:
        rows = A2.get(arm, [])
        if not rows:
            continue
        r0 = rows[0]["rate"]
        ests = [r["est"] for r in rows if r["est"]]
        doses.append((r0, med(ests), arm))
        print(f"  注入 {r0:6.1f} tok/s -> 预估中位 {med(ests):6.1f} s  "
              f"(n={len(ests)})  {ARM_CN[arm]}")
    rate_x, est_y = [], []
    for arm in DOSE_ARMS:
        for r in A2.get(arm, []):
            if r["est"]:
                rate_x.append(r["rate"])
                est_y.append(r["est"])
    rho = spearman(rate_x, est_y)
    slope = lsq_slope([math.log(x) for x in rate_x], [math.log(y) for y in est_y]) if rate_x else None
    print(f"  Spearman(注入速率, 预估值) = {rho if rho is not None else float('nan'):+.3f}"
          f"   （负 = 速率越高预估越短 = 模型把速率当速率用了）")
    print(f"  拟合 ln(est) = a + b·ln(rate)，b = {slope if slope is not None else float('nan'):+.3f}"
          f"   （b=0 完全没用；b=-1 完全当速率用）")
    # 取消机制：隐含 token 数（est × rate）随注入速率怎么走
    tok_x, tok_y = [], []
    for arm in DOSE_ARMS:
        for r in A2.get(arm, []):
            if r["est"] and r["rate"]:
                tok_x.append(r["rate"])
                tok_y.append(r["est"] * r["rate"])
    rho_tok = spearman(tok_x, tok_y) if len(tok_x) >= 3 else None
    print()
    print("  【取消机制】模型'以为'自己要写的 token 数 = 预估秒数 × 注入速率：")
    for arm in DOSE_ARMS:
        vals = [r["est"] * r["rate"] for r in A2.get(arm, []) if r["est"] and r["rate"]]
        if vals:
            print(f"    注入 {A2[arm][0]['rate']:6.1f} tok/s -> 隐含 token 中位 {med(vals):6.0f}")
    print(f"    Spearman(注入速率, 隐含 token 数) = "
          f"{rho_tok if rho_tok is not None else float('nan'):+.3f}")
    print("    若这个相关为正：速率被同时灌进了「我能写多少」和「要多久」，")
    print("    两个效应相互抵消，于是预估值对速率不敏感（上面 b≈0 就是这么来的）。")
    out["A2_dose"] = {"doses": [{"rate": a, "median_est": b, "arm": c} for a, b, c in doses],
                      "spearman_rate_vs_est": rho, "loglog_slope": slope,
                      "spearman_rate_vs_implied_tokens": rho_tok,
                      "implied_tokens_median_by_arm": {
                          arm: med([r["est"] * r["rate"] for r in A2.get(arm, [])
                                    if r["est"] and r["rate"]])
                          for arm in DOSE_ARMS}}

    # ---- A2 vs base 置换检验 ----
    print()
    print("-" * 92)
    print("A2 成对比较 vs base（med|ln(est/实测)| 越低越好）")
    print("-" * 92)
    base_err = [r["err"] for r in A2.get("base", []) if r["err"] is not None]
    out["A2_compare"] = {}
    for arm in ARM_ORDER:
        if arm == "base":
            continue
        cur = [r["err"] for r in A2.get(arm, []) if r["err"] is not None]
        if not base_err or not cur:
            continue
        c = compare_groups(base_err, cur)
        ci = c.get("ci") or (None, None)
        p = c.get("p")
        mark = ("**显著更好**" if c["delta"] < 0 and p is not None and p < 0.05
                else "**显著更差**" if c["delta"] > 0 and p is not None and p < 0.05
                else "无显著差异")
        out["A2_compare"][arm] = c
        print(f"  {ARM_CN[arm]:<26} Δ={c['delta']:+.3f} "
              f"CI=[{ci[0]:.3f}, {ci[1]:.3f}] p={p:.3f}  {mark}")
    if base_err:
        print(f"  基线 med|ln| = {med(base_err):.3f}（n={len(base_err)}）")

    # ================= B2 =================
    print()
    print("=" * 92)
    print("B2 题：纯换算（速率只在系统提示里按臂注入，题目本身不含速率）")
    print("=" * 92)
    print(f"  {'臂':<26}{'n':>3}{'隐含速率中位':>14}{'隐含/注入':>12}"
          f"{'各token档隐含速率':>34}")
    out["B2"] = {}
    for arm in ARM_ORDER:
        rows = B2.get(arm, [])
        if not rows:
            continue
        imp = [r["implied_rate"] for r in rows if r["implied_rate"]]
        inj = rows[0]["rate"]
        by_tok = {}
        for r in rows:
            if r["implied_rate"]:
                by_tok.setdefault(r["tokens"], []).append(r["implied_rate"])
        detail = "  ".join(f"{t}:{med(v):.0f}" for t, v in sorted(by_tok.items()))
        ratio = (med(imp) / inj) if (inj and imp) else None
        out["B2"][arm] = {"n": len(rows), "median_implied_rate": med(imp),
                          "injected_rate": inj, "implied_over_injected": ratio,
                          "by_tokens": {str(k): med(v) for k, v in by_tok.items()},
                          "rows": rows}
        print(f"  {ARM_CN[arm]:<26}{len(rows):>3}"
              f"{(med(imp) if imp else float('nan')):>14.1f}"
              f"{(f'{ratio:.3f}' if ratio else '-'):>12}   {detail}")
    print("  隐含速率 = token 数 ÷ 模型答的秒数 = 模型‘以为自己’的速度。")
    print("  base 行的隐含速率 = 模型没有任何外部信息时默认假设自己有多快。")

    bx, by = [], []
    for arm in DOSE_ARMS:
        for r in B2.get(arm, []):
            if r["implied_rate"]:
                bx.append(r["rate"])
                by.append(r["implied_rate"])
    if bx:
        rho2 = spearman(bx, by)
        print(f"\n  Spearman(注入速率, 隐含速率) = {rho2:+.3f}   （+1 = 完全照着注入值走）")
        out["B2_dose"] = {"spearman_rate_vs_implied": rho2,
                          "pairs": [{"injected": a, "implied": b} for a, b in zip(bx, by)]}

    # ================= echo 诊断（对照 Phase B v1） =================
    print()
    print("=" * 92)
    print("echo 诊断：把目标秒数告诉模型时，预估是不是只是抄题？")
    print("=" * 92)
    v1 = os.path.join(RAW, "phase_b_30s.jsonl")
    if os.path.exists(v1):
        v1recs = [json.loads(l) for l in open(v1, encoding="utf-8") if l.strip()]
        v1A = [r for r in v1recs if r.get("phase") == "B_A" and not r["metrics"].get("error")]
        v1echo = sum(1 for r in v1A
                     if r["parsed"].get("estimate_s") == r.get("target_s"))
        if v1A:
            print(f"  Phase B v1 的 A 题（目标秒数已告知）：{v1echo}/{len(v1A)} "
                  f"= {v1echo/len(v1A)*100:.0f}% 的预估值恰好等于目标秒数 -> 抄题，无独立估计。")
            out["v1_echo"] = {"n": len(v1A), "echo": v1echo, "rate": v1echo / len(v1A)}
    a2all = [r for rows in A2.values() for r in rows]
    if a2all:
        e2 = sum(1 for r in a2all if r["echoes_item_count"])
        print(f"  Phase B2 的 A2 题（目标秒数不告知）：{e2}/{len(a2all)} "
              f"= {e2/len(a2all)*100:.0f}% 的预估值恰好等于条目数 133 -> "
              f"{'仍有抄题' if e2 else '无抄题，预估是独立做的'}。")

    with open(os.path.join(OUT, "phase_b2_summary.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nwrote {OUT}\\phase_b2_summary.json")


if __name__ == "__main__":
    main()
