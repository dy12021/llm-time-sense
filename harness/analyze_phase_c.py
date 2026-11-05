# -*- coding: utf-8 -*-
"""Phase C 分析：模型在**生成过程中**能不能感知「已经过了多久」。

读数（每条记录）
----------------
marks     模型自己标的 (真实经过秒数 t_k, 标注值 N_k) 配对序列
slope_t   回归 N ~ t 的斜率（**理想 = 1.0**：标注与真实流逝同步）
slope_c   回归 N ~ 累计字数 的斜率（按字数推算的特征）
r2_t/r2_c 两种解释各自的拟合优度——用来区分「有内部钟」和「按字数猜」
last_err  最后一个标注 vs 真实总生成时长（med|ln|）
d_spear   段增量 ΔN 与真实段增量 Δt 的 Spearman（最直接的「过程中」指标）
const_frac 相邻标注值完全相同的比例（只会报常数 = 没有内部钟）

跨臂：置换检验。
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.analyze import compare_groups, spearman  # noqa: E402
from harness.phase_c import char_time_map, parse_marks  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

ARM_CN = {"base": "基线（无反馈）", "speed": "注入实测速率", "elapsed": "注入真实实测耗时"}
ARM_ORDER = ["base", "speed", "elapsed"]


def med(xs):
    return st.median(xs) if xs else None


def ols(xs, ys):
    """返回 (斜率, 截距, R²)。"""
    n = len(xs)
    if n < 3:
        return None, None, None
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None, None, None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    r2 = (1 - ss_res / ss_tot) if ss_tot > 0 else None
    return b, a, r2


def one_record(rec) -> dict:
    m = rec["metrics"]
    content = m.get("content") or ""
    marks = parse_marks(content)
    ctime = char_time_map(rec)
    t_gen = m.get("gen_s") or 0.0

    pairs = []
    for s, e, v in marks:
        idx = min(max(e - 1, 0), len(ctime) - 1) if ctime else None
        if idx is None:
            continue
        pairs.append({"t": ctime[idx], "v": v, "char_end": e})

    # 累计字数（正文字符数）
    cum = []
    for p in pairs:
        cum.append(p["char_end"])

    out = {"arm": rec["arm"], "trial": rec["trial"],
           "spec": rec.get("spec"),
           "gen_s": t_gen, "out_tokens": m.get("out_tokens"),
           "content_tokens": m.get("content_tokens"),
           "think_tokens": m.get("think_tokens"),
           "chars": len(content),
           "tps": m.get("tps"), "n_marks": len(pairs),
           "finish": m.get("finish_reason"),
           "injected_rate": rec.get("injected_rate"),
           "injected_elapsed_s": rec.get("injected_elapsed_s"),
           "pairs": pairs}
    # 标记是 inline 还是全堆在末尾
    if pairs and len(content):
        pos = [p["char_end"] / len(content) for p in pairs]
        out["mark_positions_rel"] = pos
        out["inline_frac"] = sum(1 for p in pos if p < 0.9) / len(pos)
        out["mark_spread"] = (max(pos) - min(pos)) if pos else None
    # 模型「以为」自己的速率
    if pairs and t_gen > 0 and pairs[-1]["v"] > 0 and content:
        out["implied_rate"] = len(content) / pairs[-1]["v"]
        out["actual_rate"] = len(content) / t_gen
        out["rate_ratio"] = out["implied_rate"] / out["actual_rate"]
        out["rate_logerr"] = abs(math.log(out["rate_ratio"]))
    if len(pairs) >= 3:
        ts = [p["t"] for p in pairs]
        vs = [p["v"] for p in pairs]
        cs = [float(x) for x in cum]
        bt, at, r2t = ols(ts, vs)
        bc, ac, r2c = ols(cs, vs)
        out["slope_t"] = bt
        out["slope_c"] = bc
        out["r2_t"] = r2t
        out["r2_c"] = r2c
        out["spearman_t_v"] = spearman(ts, vs)
        out["spearman_c_v"] = spearman(cs, vs)
        dt = [ts[i] - ts[i - 1] for i in range(1, len(ts))]
        dv = [vs[i] - vs[i - 1] for i in range(1, len(vs))]
        out["d_spearman"] = spearman(dt, dv) if len(dt) >= 3 else None
        out["const_frac"] = (sum(1 for i in range(1, len(vs)) if vs[i] == vs[i - 1])
                             / max(len(vs) - 1, 1))
        if t_gen > 0 and vs[-1] > 0:
            out["last_logerr"] = abs(math.log(vs[-1] / t_gen))
            out["last_ratio"] = vs[-1] / t_gen
        else:
            out["last_logerr"] = None
            out["last_ratio"] = None
        out["last_mark"] = vs[-1]
        out["first_mark"] = vs[0]

    # ---- 「模型到底用了哪个外部信息」：三个互相独立的量纲，对照看
    ct = m.get("content_tokens") or 0
    if pairs and out.get("last_mark"):
        lm = out["last_mark"]
        # (a) 模型隐含的速率：它认为「总 token ÷ 标注总秒数」
        out["implied_tps"] = ct / lm if lm > 0 else None
        # (b) 若模型用的是注入速率，它推出的总时长应该是 token/injected_rate
        ir = rec.get("injected_rate")
        out["expect_s_from_rate"] = (ct / ir) if (ir and ct) else None
        if out["expect_s_from_rate"]:
            out["used_rate_ratio"] = lm / out["expect_s_from_rate"]
        # (c) 若模型摊的是注入的绝对耗时，它推出的总时长应 ≈ 注入值
        # 注意：base 臂的注入值只是「记录用」（它根本没看到），不能拿来算比例
        ie = rec.get("injected_elapsed_s")
        if rec["arm"] == "elapsed":
            out["expect_s_from_elapsed"] = ie if ie else None
            if ie:
                out["used_elapsed_ratio"] = lm / ie
        # (d) 模型隐含速率 vs 注入速率
        if ir and out.get("implied_tps"):
            out["implied_vs_injected_tps"] = out["implied_tps"] / ir

    # ---- 思维链证据：它有没有在推理里「看到」我们注入的那个数
    rs = (m.get("reasoning") or "")
    out["reasoning"] = rs[:1200]
    nums = []
    for tok in re.findall(r"\d+(?:\.\d+)?", rs):
        try:
            nums.append(float(tok))
        except ValueError:
            pass
    ir = rec.get("injected_rate")
    if ir and nums:
        out["reasoning_cites_rate"] = any(abs(x - ir) / ir <= 0.15 for x in nums)
    ie = rec.get("injected_elapsed_s")
    if ie and nums:
        out["reasoning_cites_elapsed"] = any(abs(x - ie) / ie <= 0.15 for x in nums)
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAW, "phase_c.jsonl")
    outname = sys.argv[2] if len(sys.argv) > 2 else "phase_c_summary.json"
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    ok = [r for r in recs if not r["metrics"].get("error")]
    print(f"载入 {len(recs)} 条（无错误 {len(ok)} 条）自 {path}\n")

    ivs = sorted((r["metrics"]["t_request"], r["metrics"]["t_last"]) for r in recs)
    ov = sum(1 for i in range(len(ivs) - 1) if ivs[i][1] > ivs[i + 1][0] + 1e-6)
    gaps = [ivs[i + 1][0] - ivs[i][1] for i in range(len(ivs) - 1)]
    print(f"串行性：{len(ivs)} 次调用，重叠 {ov} 次 -> {'成立 ✓' if ov == 0 else '存在并发 ✗'}"
          + (f"；相邻间隔中位 {med(gaps)*1000:.2f}ms" if gaps else ""), flush=True)
    print()

    rows = [one_record(r) for r in ok]
    usable = [r for r in rows if r.get("slope_t") is not None]

    print("=" * 100)
    print("每条记录")
    print("=" * 100)
    print(f"  {'臂':<20}{'k':>3}{'生成s':>8}{'正文tok':>8}{'标记数':>7}{'slope_t':>9}"
          f"{'R²(t)':>8}{'R²(字数)':>10}{'末标注s':>9}{'真实s':>8}{'末标注/真实':>12}")
    for r in rows:
        print(f"  {ARM_CN.get(r['arm'], r['arm']):<20}{r['trial']:>3}"
              f"{r['gen_s']:>8.1f}{r['content_tokens']:>8}{r['n_marks']:>7}"
              f"{(f'{r['slope_t']:.3f}' if r.get('slope_t') is not None else '-'):>9}"
              f"{(f'{r['r2_t']:.3f}' if r.get('r2_t') is not None else '-'):>8}"
              f"{(f'{r['r2_c']:.3f}' if r.get('r2_c') is not None else '-'):>10}"
              f"{(f'{r.get('last_mark'):.0f}' if r.get('last_mark') is not None else '-'):>9}"
              f"{r['gen_s']:>8.1f}"
              f"{(f'{r['last_ratio']:.2f}' if r.get('last_ratio') is not None else '-'):>12}")

    print()
    print("=" * 100)
    print("按臂汇总")
    print("=" * 100)
    print(f"  {'臂':<20}{'n':>3}{'生成s中位':>10}{'标记中位':>9}{'slope_t中位':>12}"
          f"{'R²(t)':>8}{'R²(字数)':>10}{'增量Spearman':>12}{'常数率':>9}"
          f"{'末标注/真实':>12}{'inline率':>9}{'速率比':>9}")
    out = {"arms": {}}

    def fnum(v, f="{:+.3f}"):
        return f.format(v) if isinstance(v, (int, float)) else "-"

    for arm in ARM_ORDER:
        rs = [r for r in usable if r["arm"] == arm]
        all_arm = [r for r in rows if r["arm"] == arm]   # 含 0 标记的（合规失败）
        if not rs and not all_arm:
            continue
        s = {
            "n": len(rs),
            "median_gen_s": med([r["gen_s"] for r in rs]),
            "median_marks": med([r["n_marks"] for r in rs]),
            "median_slope_t": med([r["slope_t"] for r in rs]),
            "median_r2_t": med([r["r2_t"] for r in rs]),
            "median_r2_c": med([r["r2_c"] for r in rs]),
            "median_d_spearman": med([r["d_spearman"] for r in rs
                                      if r.get("d_spearman") is not None]),
            "median_const_frac": med([r["const_frac"] for r in rs]),
            "median_last_ratio": med([r["last_ratio"] for r in rs
                                      if r.get("last_ratio") is not None]),
            "median_last_logerr": med([r["last_logerr"] for r in rs
                                       if r.get("last_logerr") is not None]),
            "median_inline_frac": med([r["inline_frac"] for r in rs
                                       if r.get("inline_frac") is not None]),
            "median_rate_ratio": med([r["rate_ratio"] for r in rs
                                      if r.get("rate_ratio") is not None]),
            # 标记丢失：模型规划了时间标记但正文里一个都没写
            "n_zero_marks": sum(1 for r in all_arm if not r.get("n_marks")),
            "n_runs": len(all_arm),
            "n_marks_total": sum(r.get("n_marks") or 0 for r in all_arm),
        }
        out["arms"][arm] = s
        print(f"  {ARM_CN.get(arm, arm):<20}{s['n']:>3}"
              f"{fnum(s['median_gen_s'], '{:.1f}'):>10}"
              f"{fnum(s['median_marks'], '{:.0f}'):>9}"
              f"{fnum(s['median_slope_t']):>12}"
              f"{fnum(s['median_r2_t']):>8}{fnum(s['median_r2_c']):>10}"
              f"{fnum(s['median_d_spearman']):>12}"
              f"{fnum(s['median_const_frac'], '{:.2f}'):>9}"
              f"{fnum(s['median_last_ratio'], '{:.2f}'):>12}"
              f"{fnum(s['median_inline_frac'], '{:.2f}'):>9}"
              f"{fnum(s['median_rate_ratio'], '{:.2f}'):>9}")
    print("  slope_t = 1.0 表示标注与真实流逝同步（理想）；R²(字数) 明显高于 R²(t) = 按字数瞎猜。")
    print("  末标注/真实 <1 = 低估，>1 = 高估；速率比 = 模型以为的速率 ÷ 真实速率（1 = 准）。")
    print("  inline率 = 落在正文 90% 之前的标记占比（全堆在末尾则接近 0）。")

    print()
    print("=" * 100)
    print("跨轮：模型标注的「总耗时」是否随真实耗时快慢变化")
    print("=" * 100)
    print("  同一臂内部，如果模型有任何时间感，真实跑得越慢的一次，标注总秒数应当越大。")
    print("  Spearman ≈ 0 = 标注与真实快慢无关（纯靠字数/结构瞎猜）。")
    out["cross_run"] = {}
    for scope, rs in ([("全部", usable)] +
                      [(f"{ARM_CN.get(a, a)}", [r for r in usable if r["arm"] == a])
                       for a in ARM_ORDER]):
        lm = [r.get("last_mark") for r in rs]
        gs = [r.get("gen_s") for r in rs]
        pairs_ = [(a, b) for a, b in zip(lm, gs) if a is not None and b is not None]
        # 步长口径：模型「心里」一节写多久
        stp = []
        for r in rs:
            ps = r.get("pairs") or []
            if len(ps) >= 3:
                stp.append((med([ps[i]["v"] - ps[i - 1]["v"] for i in range(1, len(ps))]),
                            r.get("gen_s")))
        if len(pairs_) < 4 and len(stp) < 4:
            continue
        rec_out = {"n": len(pairs_)}
        if len(pairs_) >= 4:
            rec_out["spearman_marked_vs_real"] = spearman([p[0] for p in pairs_],
                                                          [p[1] for p in pairs_])
        if len(stp) >= 4:
            rec_out["spearman_step_vs_real"] = spearman([p[0] for p in stp],
                                                        [p[1] for p in stp])
            rec_out["n_step"] = len(stp)
        out["cross_run"][scope] = rec_out
        sp1 = rec_out.get("spearman_marked_vs_real")
        sp2 = rec_out.get("spearman_step_vs_real")
        print(f"  {scope:<20} n={len(pairs_):>2}  Spearman(标注总秒, 真实耗时) = "
              f"{('%+.3f' % sp1) if sp1 is not None else '—':>7}   "
              f"Spearman(步长, 真实耗时) = {('%+.3f' % sp2) if sp2 is not None else '—':>7}")
    print()

    print()
    print("=" * 100)
    print("模型到底用了哪个外部信息")
    print("=" * 100)
    print(f"  {'臂':<20}{'n':>3}{'标记总/真实':>14}{'隐含tok/s':>12}{'隐含/注入':>12}"
          f"{'标记/(token/注入速率)':>22}{'标记/注入耗时':>16}")
    for arm in ARM_ORDER:
        rs = [r for r in usable if r["arm"] == arm]
        if not rs:
            continue
        s = {
            "median_marked_over_real": med([r["last_ratio"] for r in rs
                                            if r.get("last_ratio") is not None]),
            "median_implied_tps": med([r.get("implied_tps") for r in rs
                                       if r.get("implied_tps") is not None]),
            "median_implied_vs_injected_tps": med([r.get("implied_vs_injected_tps")
                                                    for r in rs
                                                    if r.get("implied_vs_injected_tps")
                                                    is not None]),
            "median_used_rate_ratio": med([r.get("used_rate_ratio") for r in rs
                                           if r.get("used_rate_ratio") is not None]),
            "median_used_elapsed_ratio": med([r.get("used_elapsed_ratio") for r in rs
                                              if r.get("used_elapsed_ratio") is not None]),
        }
        out.setdefault("arms", {}).setdefault(arm, {}).update(s)
        print(f"  {ARM_CN.get(arm, arm):<20}{len(rs):>3}"
              f"{fnum(s['median_marked_over_real'], '{:.2f}'):>14}"
              f"{fnum(s['median_implied_tps'], '{:.1f}'):>12}"
              f"{fnum(s['median_implied_vs_injected_tps'], '{:.2f}'):>12}"
              f"{fnum(s['median_used_rate_ratio'], '{:.2f}'):>22}"
              f"{fnum(s['median_used_elapsed_ratio'], '{:.2f}'):>16}")
    print("  标记/(token/注入速率) ≈ 1 → 模型真的用注入速率换算了总时长；"
          "标记/注入耗时 ≈ 1 → 模型把注入的绝对量摊到了过程里。")
    print()

    # ---- 模型心里那个「速率」是不是一个固定默认值
    print("=" * 100)
    print("模型心里那个速率：是「量出来的」还是「默认假设的」")
    print("=" * 100)
    print("  隐含速率 = 正文 token ÷ 标注总秒。若模型在感知真实流逝，")
    print("  隐含速率应当随真实速率一起变；若是默认值，它会**固定在某个数上**。")
    out["implied_rate"] = {}
    for scope, rs in [("全部", usable)] + [(a, [r for r in usable if r["arm"] == a])
                                           for a in ARM_ORDER]:
        pairs_ = [(r.get("implied_tps"), r.get("tps")) for r in rs
                   if r.get("implied_tps") and r.get("tps")]
        if len(pairs_) < 3:
            continue
        imp = [p[0] for p in pairs_]
        real = [p[1] for p in pairs_]
        sp = spearman(imp, real) if len(pairs_) >= 4 else None
        cv_i = (st.pstdev(imp) / st.mean(imp)) if st.mean(imp) else None
        cv_r = (st.pstdev(real) / st.mean(real)) if st.mean(real) else None
        out["implied_rate"][scope] = {
            "n": len(pairs_), "median_implied_tps": med(imp),
            "median_real_tps": med(real),
            "cv_implied": cv_i, "cv_real": cv_r,
            "spearman_implied_vs_real": sp}
        print(f"  {scope:<20} n={len(pairs_):>2}  隐含速率中位 {med(imp):5.1f} tok/s"
              f"（CV {cv_i:.3f}）   真实速率中位 {med(real):5.1f} tok/s（CV {cv_r:.3f}）"
              + (f"   Spearman {sp:+.3f}" if sp is not None else ""))
    print("  判读：若隐含速率与真实速率**正相关且同量级** → 模型在感知流逝；")
    print("  若两者**不相关**或差着量级 → 模型心里那把尺子是固定默认值 / 纯猜。")
    print()


    # ---- 传输层：代理 vs 直连有没有污染速率分布
    print("=" * 100)
    print("传输层检查（代理 vs 直连）")
    print("=" * 100)
    by_tr = {}
    for r in usable:
        by_tr.setdefault(r.get("transport") or "(未标注=旧代理)", []).append(r)
    out["transport"] = {}
    if len(by_tr) > 1:
        print(f"  {'传输':<20}{'n':>3}{'真实s中位':>11}{'tps中位':>10}{'首标记真实时刻中位':>14}")
        for tr, rs in by_tr.items():
            ttf = [r["pairs"][0]["t"] for r in rs if r.get("pairs")]
            row = {"n": len(rs),
                   "median_gen_s": med([r["gen_s"] for r in rs]),
                   "median_tps": med([r.get("tps") for r in rs]),
                   "median_first_mark_t": med(ttf) if ttf else None}
            out["transport"][tr] = row
            print(f"  {tr:<20}{row['n']:>3}{row['median_gen_s']:>11.1f}"
                  f"{row['median_tps']:>10.1f}"
                  f"{(row['median_first_mark_t'] if row['median_first_mark_t'] is not None else float('nan')):>14.2f}")
        print("  两组速率分布重叠 → 传输层切换没有污染结论。")
    else:
        tr0 = list(by_tr)[0] if by_tr else "—"
        rs0 = by_tr.get(tr0, [])
        out["transport"] = {tr0: {"n": len(rs0)}}
        print(f"  本批全部走同一传输（{tr0}），n={len(rs0)}，无需对比。")
    print()

    print("=" * 100)
    print("跨臂比较（vs base，置换检验）")
    print("=" * 100)
    base = [r for r in usable if r["arm"] == "base"]
    out["compare"] = {}
    for metric, label, lower_better in (("last_logerr", "末标注 vs 真实总耗时", True),
                                        ("rate_logerr", "隐含速率 vs 真实速率", True),
                                        ("d_spearman", "段增量 Spearman", False)):
        b = [r[metric] for r in base if r.get(metric) is not None]
        if not b:
            continue
        for arm in ("speed", "elapsed"):
            cur = [r[metric] for r in usable
                   if r["arm"] == arm and r.get(metric) is not None]
            if not cur:
                continue
            c = compare_groups(b, cur)
            ci = c.get("ci") or (None, None)
            p = c.get("p")
            d = c.get("delta")
            if d is None or p is None:
                continue
            if lower_better:
                mark = ("**显著更好**" if d < 0 and p < 0.05 else
                        "**显著更差**" if d > 0 and p < 0.05 else "无显著差异")
            else:
                mark = ("**显著更好**" if d > 0 and p < 0.05 else
                        "**显著更差**" if d < 0 and p < 0.05 else "无显著差异")
            out["compare"][f"{metric}|{arm}"] = c
            print(f"  {label:<22}{ARM_CN.get(arm, arm):<18} Δ={d:+.3f} "
                  f"CI=[{ci[0]:.3f}, {ci[1]:.3f}] p={p:.3f}  {mark}")

    with open(os.path.join(OUT, outname), "w", encoding="utf-8") as f:
        json.dump({"rows": rows, **out}, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nwrote {os.path.join(OUT, outname)}")


if __name__ == "__main__":
    main()
