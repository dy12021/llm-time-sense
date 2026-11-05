# -*- coding: utf-8 -*-
"""Analysis: calibration, fixed-duration hitting, long-horizon drift.

Metric conventions (stated once, used everywhere):
  ratio      = estimate / actual          (1.0 = perfect)
  logerr     = |ln(ratio)|               (symmetric, comparable across scales)
  signed_log = ln(ratio)                 (bias direction)
  For fixed-duration tasks: hit_err = (actual_gen_s - target_s) / target_s
"""
from __future__ import annotations

import json
import math
import os
import statistics as st
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import tasks as T  # noqa: E402

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")


def load(path: str | None = None) -> list[dict]:
    path = path or os.path.join(RAW, "records.jsonl")
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return recs


def _safe(fn, seq, default=None):
    seq = [x for x in seq if x is not None]
    if not seq:
        return default
    try:
        return fn(seq)
    except Exception:
        return default


def _rank(xs: list[float]) -> list[float]:
    """average ranks for spearman"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = _rank(a), _rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if da == 0 or db == 0:
        return None
    return num / (da * db)


def bootstrap_ci(xs: list[float], stat=st.median, n=2000, seed=7):
    import random
    rnd = random.Random(seed)
    if len(xs) < 2:
        return (None, None)
    vals = []
    for _ in range(n):
        vals.append(stat([rnd.choice(xs) for _ in xs]))
    vals.sort()
    return (vals[int(0.025 * n)], vals[int(0.975 * n)])


def summarise(name: str, pairs: list[tuple[float, float]], min_actual: float = 0.2) -> dict:
    """pairs = (estimate, actual)"""
    rows = []
    for est, act in pairs:
        if est is None or act is None or act < min_actual or est <= 0:
            continue
        r = est / act
        rows.append({"estimate": est, "actual": act, "ratio": r,
                     "logerr": abs(math.log(r)), "signed_log": math.log(r)})
    if not rows:
        return {"name": name, "n": 0}
    ratios = [r["ratio"] for r in rows]
    return {
        "name": name,
        "n": len(rows),
        "median_ratio": _safe(st.median, ratios),
        "mean_ratio": _safe(st.mean, ratios),
        "median_logerr": _safe(st.median, [r["logerr"] for r in rows]),
        "mean_logerr": _safe(st.mean, [r["logerr"] for r in rows]),
        "bias_log": _safe(st.mean, [r["signed_log"] for r in rows]),
        "spearman": spearman([r["estimate"] for r in rows], [r["actual"] for r in rows]),
        "ratio_ci": bootstrap_ci(ratios),
        "rows": rows,
    }


def build(recs: list[dict]) -> dict:
    # ---------- T1 copy-check: did the model just echo the number it was given?
    # NOTE: index by the record's own cycle, then look up cycle-1 for the
    # previous turn. (Keying by cycle-1 and looking up cycle-1 returns the
    # record itself -- that bug once made the model look like a copier.)
    by_cycle = {}
    for r in recs:
        by_cycle[(r["session_id"], r["cycle"])] = r
    copy_check = defaultdict(list)
    self_repeat = defaultdict(list)
    for r in recs:
        if r["kind"] == "S1_report" and not r["metrics"].get("error"):
            pv = by_cycle.get((r["session_id"], r["cycle"] - 1))
            if pv is None:
                continue
            est = r["parsed"].get("estimate_s")
            actual = pv["metrics"]["duration_s"]
            if est is None:
                continue
            copy_check[r["arm"]].append({
                "est": est, "prev_actual": actual,
                "abs_diff": abs(est - actual),
                "copied": abs(est - actual) <= 0.5,
                "ratio": est / actual if actual else None,
            })
            # S1's report turn directly follows the estimate turn of the same
            # task -> the model can simply repeat its own earlier prediction.
            prev_est = pv["parsed"].get("estimate_s")
            if prev_est is not None:
                self_repeat[r["arm"]].append({
                    "report_est": est, "own_prev_est": prev_est,
                    "repeated": abs(est - prev_est) < 1e-9,
                })

    # ---------------- T1: report duration of the previous reply -------------
    # split by source: S1 (preceded by the model's own estimate -> contaminated)
    # vs S3 (no preceding estimate -> clean)
    t1 = defaultdict(list)
    t1_clean = defaultdict(list)
    t1_contam = defaultdict(list)
    for r in recs:
        if r["kind"] == "S1_report" and not r["metrics"].get("error"):
            t1[r["arm"]].append((r["parsed"].get("estimate_s"), r["metrics"]["duration_s"]))
            t1_contam[r["arm"]].append((r["parsed"].get("estimate_s"), r["metrics"]["duration_s"]))
        if r["kind"] == "S3_task" and r["question"] == "prev_duration" and not r["metrics"].get("error"):
            t1[r["arm"]].append((r["parsed"].get("estimate_s"), r["metrics"]["duration_s"]))
            t1_clean[r["arm"]].append((r["parsed"].get("estimate_s"), r["metrics"]["duration_s"]))

    # ---------------- T3: pre-estimate of its own reply ----------------------
    # the actual duration of the same turn is the turn's own duration
    t3 = defaultdict(list)
    for r in recs:
        if r["kind"] == "S1_estimate" and not r["metrics"].get("error"):
            t3[r["arm"]].append((r["parsed"].get("estimate_s"), r["metrics"]["duration_s"]))

    # ---------------- T2: fixed duration -------------------------------------
    t2 = defaultdict(list)
    t2_plan = defaultdict(list)
    for r in recs:
        if r["kind"] == "S2_write" and not r["metrics"].get("error"):
            target = r["parsed"].get("target_s")
            gen = r["metrics"]["gen_s"]
            t2[r["arm"]].append({"target_s": target, "gen_s": gen, "duration_s": r["metrics"]["duration_s"],
                                 "tokens": r["metrics"]["out_tokens"],
                                 "out_tokens": r["metrics"]["content_tokens"],
                                 "think_tokens": r["metrics"]["think_tokens"],
                                 "tps": r["metrics"]["tps"],
                                 "hit_err": (gen - target) / target if target else None})
        if r["kind"] == "S2_probe" and not r["metrics"].get("error"):
            prev = [x for x in recs if x["session_id"] == r["session_id"]
                    and x["kind"] == "S2_write" and x["cycle"] == r["cycle"] - 1]
            if prev:
                w = prev[0]
                claimed = r["parsed"].get("tokens")
                if isinstance(claimed, (int, float)):
                    t2_plan[r["arm"]].append({
                        "claimed_tokens": claimed,
                        "actual_tokens": w["metrics"]["out_tokens"],
                        "actual_out_tokens": w["metrics"]["content_tokens"],
                        "target_s": w["parsed"]["target_s"],
                        "tps": w["metrics"]["tps"],
                        "strategy": r["parsed"].get("strategy") or "",
                    })

    # ---------------- T4: long horizon --------------------------------------
    t4 = defaultdict(list)
    for r in recs:
        if (r["kind"] == "S3_task" and r["question"] == "elapsed_since_start"
                and not r["metrics"].get("error")):
            t4[r["arm"]].append({
                "cycle": r["cycle"],
                "estimate_s": r["parsed"].get("estimate_s"),
                "actual_s": r.get("session_elapsed_at_prompt_s"),
            })

    return {"t1": t1, "t1_clean": t1_clean, "t1_contam": t1_contam,
            "t3": t3, "t2": t2, "t2_plan": t2_plan, "t4": t4,
            "copy_check": copy_check, "self_repeat": self_repeat}


def compare_groups(a: list[float], b: list[float], seed: int = 11) -> dict:
    """Compare two arms on a metric (lower is better).

    Returns bootstrap CI of the median difference (b - a) and a two-sided
    permutation p-value. Non-parametric because n is small.
    """
    import random
    rnd = random.Random(seed)
    if len(a) < 3 or len(b) < 3:
        return {"n_a": len(a), "n_b": len(b), "delta": None, "ci": (None, None), "p": None}

    def med(v):
        return st.median(v)

    delta = med(b) - med(a)
    # bootstrap
    boots = []
    for _ in range(2000):
        ba = [rnd.choice(a) for _ in a]
        bb = [rnd.choice(b) for _ in b]
        boots.append(med(bb) - med(ba))
    boots.sort()
    ci = (boots[50], boots[1949])
    # permutation
    pool = a + b
    na = len(a)
    obs = abs(delta)
    hits = 0
    nperm = 5000
    for _ in range(nperm):
        rnd.shuffle(pool)
        d = abs(med(pool[na:]) - med(pool[:na]))
        if d >= obs - 1e-12:
            hits += 1
    p = (hits + 1) / (nperm + 1)
    return {"n_a": len(a), "n_b": len(b), "delta": delta, "ci": ci, "p": p}


def logerrs(pairs) -> list[float]:
    out = []
    for est, act in pairs:
        if est is None or act is None or act < 0.2 or est <= 0:
            continue
        out.append(abs(math.log(est / act)))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    recs = load(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"loaded {len(recs)} records")
    errs = [r for r in recs if r["metrics"].get("error")]
    if errs:
        print(f"WARNING: {len(errs)} turns had errors; first: {errs[0]['metrics']['error'][:160]}")

    b = build(recs)
    out = {}

    lines = []

    def emit(s=""):
        print(s)
        lines.append(s)

    emit("=" * 78)
    emit("T1  报出上一条回复用时 (post-hoc duration report)")
    emit("=" * 78)
    emit(f"{'arm':<14}{'n':>4}{'median ratio':>14}{'med |ln|':>11}{'bias(ln)':>10}{'spearman':>10}")
    out["t1"] = {}
    for arm, pairs in sorted(b["t1"].items()):
        s = summarise(f"T1/{arm}", pairs)
        out["t1"][arm] = {k: v for k, v in s.items() if k != "rows"}
        emit(f"{arm:<14}{s.get('n',0):>4}{(s.get('median_ratio') or 0):>14.3f}"
             f"{(s.get('median_logerr') or 0):>11.3f}{(s.get('bias_log') or 0):>10.3f}"
             f"{(s.get('spearman') if s.get('spearman') is not None else float('nan')):>10.3f}")

    emit()
    emit("=" * 78)
    emit("T3  回答前预估本条回复耗时 (pre-estimate)")
    emit("=" * 78)
    emit(f"{'arm':<14}{'n':>4}{'median ratio':>14}{'med |ln|':>11}{'bias(ln)':>10}{'spearman':>10}")
    out["t3"] = {}
    for arm, pairs in sorted(b["t3"].items()):
        s = summarise(f"T3/{arm}", pairs)
        out["t3"][arm] = {k: v for k, v in s.items() if k != "rows"}
        emit(f"{arm:<14}{s.get('n',0):>4}{(s.get('median_ratio') or 0):>14.3f}"
             f"{(s.get('median_logerr') or 0):>11.3f}{(s.get('bias_log') or 0):>10.3f}"
             f"{(s.get('spearman') if s.get('spearman') is not None else float('nan')):>10.3f}")

    emit()
    emit("=" * 78)
    emit("T2  固定时长命中 (target gen seconds)")
    emit("=" * 78)
    emit(f"{'arm':<14}{'n':>4}{'med |hit_err|':>14}{'median gen':>12}{'median tokens':>15}")
    out["t2"] = {}
    for arm, rows in sorted(b["t2"].items()):
        errs_ = [abs(x["hit_err"]) for x in rows if x["hit_err"] is not None]
        gens = [x["gen_s"] for x in rows]
        toks = [x["tokens"] for x in rows]
        out["t2"][arm] = {"n": len(rows), "median_abs_hit_err": _safe(st.median, errs_),
                           "median_gen_s": _safe(st.median, gens), "median_tokens": _safe(st.median, toks),
                           "rows": rows}
        emit(f"{arm:<14}{len(rows):>4}{(_safe(st.median, errs_) or 0):>14.3f}"
             f"{(_safe(st.median, gens) or 0):>12.2f}{(_safe(st.median, toks) or 0):>15.0f}")

    emit()
    emit("  per-target detail (arm x target):")
    emit(f"    {'arm':<14}{'target':>8}{'n':>4}{'med gen':>10}{'med |err|':>11}{'out tok':>9}{'think tok':>11}")
    out["t2_detail"] = {}
    for arm, rows in sorted(b["t2"].items()):
        for tgt in sorted({x["target_s"] for x in rows if x["target_s"]}):
            sub = [x for x in rows if x["target_s"] == tgt]
            e = [abs(x["hit_err"]) for x in sub if x["hit_err"] is not None]
            g = [x["gen_s"] for x in sub]
            ot = [x["out_tokens"] for x in sub]
            tt = [x["think_tokens"] for x in sub]
            out["t2_detail"][f"{arm}|{tgt}"] = {"n": len(sub), "median_gen_s": _safe(st.median, g),
                                                 "median_abs_hit_err": _safe(st.median, e),
                                                 "median_out_tokens": _safe(st.median, ot),
                                                 "median_think_tokens": _safe(st.median, tt)}
            emit(f"    {arm:<14}{tgt:>8}{len(sub):>4}{(_safe(st.median,g) or 0):>10.2f}"
                 f"{(_safe(st.median,e) or 0):>11.3f}{(_safe(st.median,ot) or 0):>9.0f}"
                 f"{(_safe(st.median,tt) or 0):>11.0f}")

    emit()
    emit("=" * 78)
    emit("T2b 模型自报 token 数 vs 实际 (长度自感知)")
    emit("=" * 78)
    out["t2_plan"] = {}
    for arm, rows in sorted(b["t2_plan"].items()):
        rel = []
        for x in rows:
            if x["actual_tokens"] > 0:
                rel.append(x["claimed_tokens"] / x["actual_tokens"])
        out["t2_plan"][arm] = {"n": len(rows), "median_ratio": _safe(st.median, rel),
                               "rows": rows}
        emit(f"  {arm:<14} n={len(rows):<4} median claimed/actual = "
             f"{_safe(st.median, rel) if rel else float('nan'):.3f}")
    for arm, rows in sorted(b["t2_plan"].items()):
        for s in {x["strategy"] for x in rows if x["strategy"]} :
            pass
    emit("  sample strategies:")
    seen = set()
    for arm, rows in sorted(b["t2_plan"].items()):
        for x in rows:
            s = (x["strategy"] or "").strip().replace("\n", " ")
            if s and s not in seen:
                seen.add(s)
                emit(f"    [{arm}] {s[:150]}")

    emit()
    emit("=" * 78)
    emit("T4  长期：会话已过秒数的估计")
    emit("=" * 78)
    out["t4"] = {}
    for arm, rows in sorted(b["t4"].items()):
        pairs = [(x["estimate_s"], x["actual_s"]) for x in rows if x["actual_s"]]
        s = summarise(f"T4/{arm}", pairs)
        out["t4"][arm] = {k: v for k, v in s.items() if k != "rows"}
        out["t4"][arm]["rows"] = rows
        emit(f"  {arm:<14} n={s.get('n',0):<3} median ratio={_safe(st.median,[r['ratio'] for r in s.get('rows',[])]) or 0:.3f}"
             f"  med |ln|={s.get('median_logerr') or 0:.3f}"
             f"  spearman={s.get('spearman') if s.get('spearman') is not None else float('nan'):.3f}")

    emit()
    emit("=" * 78)
    emit("T1b 拆分：S3 干净样本 vs S1 被污染样本")
    emit("=" * 78)
    emit("  S1 的 report 轮紧跟在自己的预估轮之后，模型可以直接复读上一轮的数字；")
    emit("  S3 的 prev_duration 问句前没有预估轮，因此不含这一污染。")
    emit(f"  {'arm':<14}{'S3干净 n':>10}{'med|ln|':>10}{'spearman':>10}   "
         f"{'S1污染 n':>10}{'med|ln|':>10}{'spearman':>10}")
    out["t1_split"] = {}
    for arm in T.ARMS:
        sc = summarise(f"T1clean/{arm}", b["t1_clean"].get(arm, []))
        so = summarise(f"T1contam/{arm}", b["t1_contam"].get(arm, []))
        out["t1_split"][arm] = {
            "clean": {k: v for k, v in sc.items() if k != "rows"},
            "contam": {k: v for k, v in so.items() if k != "rows"},
        }
        emit(f"  {arm:<14}{sc.get('n',0):>10}{(sc.get('median_logerr') or 0):>10.3f}"
             f"{(sc.get('spearman') if sc.get('spearman') is not None else float('nan')):>10.3f}   "
             f"{so.get('n',0):>10}{(so.get('median_logerr') or 0):>10.3f}"
             f"{(so.get('spearman') if so.get('spearman') is not None else float('nan')):>10.3f}")

    emit()
    emit("=" * 78)
    emit("T1c 抄数检验：模型是否直接复述被告知的上一周期秒数")
    emit("=" * 78)
    out["copy_check"] = {}
    emit(f"  {'arm':<14}{'n':>4}{'抄中率(±0.5s)':>16}{'median|差|':>12}{'median ratio':>14}")
    for arm, rows in sorted(b["copy_check"].items()):
        if not rows:
            continue
        hit = sum(1 for x in rows if x["copied"]) / len(rows)
        md = _safe(st.median, [x["abs_diff"] for x in rows])
        mr = _safe(st.median, [x["ratio"] for x in rows if x["ratio"]])
        out["copy_check"][arm] = {"n": len(rows), "copy_rate": hit,
                                  "median_abs_diff": md, "median_ratio": mr}
        emit(f"  {arm:<14}{len(rows):>4}{hit:>16.0%}{md:>12.2f}{mr:>14.3f}")
    emit("  说明：提示词要求「取整数」，1.9 秒会被截断成 1 —— 这是所有臂共有的加性偏置，")
    emit("        臂间比较仍然成立；「抄中率」用 ±0.5 秒容差来吸收这个整数化。")

    emit()
    emit("  自我复读率（复读自己上一轮给出的估计，而不是去感知真实耗时）：")
    out["self_repeat"] = {}
    emit(f"    {'arm':<14}{'n':>4}{'复读率':>10}{'median|报告-自估|':>18}")
    for arm, rows in sorted(b["self_repeat"].items()):
        if not rows:
            continue
        rep = sum(1 for x in rows if x["repeated"]) / len(rows)
        md = _safe(st.median, [abs(x["report_est"] - x["own_prev_est"]) for x in rows])
        out["self_repeat"][arm] = {"n": len(rows), "repeat_rate": rep, "median_abs_diff": md}
        emit(f"    {arm:<14}{len(rows):>4}{rep:>10.0%}{md:>18.2f}")
    emit("    复读率高 = 该臂的「报用时」主要在抄自己的预测，不构成对真实耗时的感知。")

    emit()
    emit("=" * 78)
    emit("服务端吞吐的波动（TPS 本身就是噪声源）")
    emit("=" * 78)
    tps_all = [r["metrics"]["tps"] for r in recs
               if not r["metrics"].get("error") and r["metrics"]["tps"] > 0]
    if tps_all:
        import statistics
        med = st.median(tps_all)
        p10 = sorted(tps_all)[int(0.1 * len(tps_all))]
        p90 = sorted(tps_all)[int(0.9 * len(tps_all))]
        cv = statistics.pstdev(tps_all) / med if med else 0
        # TPS spread restricted to turns with a decent token count (>=150),
        # where the measurement is not dominated by fixed overheads
        big = [r["metrics"]["tps"] for r in recs
               if not r["metrics"].get("error") and r["metrics"]["out_tokens"] >= 150]
        big_med = st.median(big) if big else None
        big_p10 = sorted(big)[int(0.1 * len(big))] if big else None
        big_p90 = sorted(big)[int(0.9 * len(big))] if big else None
        out["tps_noise"] = {
            "n": len(tps_all), "median": med, "p10": p10, "p90": p90, "cv": cv,
            "n_big": len(big), "big_median": big_med, "big_p10": big_p10, "big_p90": big_p90,
            "big_ratio_p90_p10": (big_p90 / big_p10) if big_p10 else None,
        }
        emit(f"  全部轮次 n={len(tps_all)}：TPS 中位数 {med:.1f}，p10–p90 = {p10:.1f}–{p90:.1f}，变异系数 {cv:.2f}")
        if big:
            emit(f"  仅取输出≥150 token 的轮次 n={len(big)}：中位数 {big_med:.1f}，"
                 f"p10–p90 = {big_p10:.1f}–{big_p90:.1f}（p90/p10 = {big_p90 / big_p10:.2f}×）")
        emit("  含义：时长 ≈ token 数 ÷ TPS。即使模型完美知道自己的 token 数，")
        emit("        TPS 自身 2–3 倍的波动也足以让「算准时长」变得不可能。")

    emit()
    emit("=" * 78)
    emit("成对比较（每个臂 vs base，越负越好；置换检验 p 值）")
    emit("=" * 78)
    out["compare"] = {}
    task_sets = {
        "T1": {arm: logerrs(pairs) for arm, pairs in b["t1"].items()},
        "T3": {arm: logerrs(pairs) for arm, pairs in b["t3"].items()},
        "T4": {arm: logerrs([(x["estimate_s"], x["actual_s"]) for x in rows if x["actual_s"]])
               for arm, rows in b["t4"].items()},
    }
    for tname, arms_map in task_sets.items():
        emit(f"  -- {tname} --")
        base = arms_map.get("base", [])
        for arm in T.ARMS:
            if arm == "base":
                continue
            c = compare_groups(base, arms_map.get(arm, []))
            out["compare"][f"{tname}|{arm}"] = c
            emit(f"    {arm:<14} n={c['n_a']}/{c['n_b']:<4} "
                 f"Δ={('%.3f' % c['delta']) if c['delta'] is not None else 'n/a':>7} "
                 f"CI=[{('%.3f' % c['ci'][0]) if c['ci'][0] is not None else 'n/a'}, "
                 f"{('%.3f' % c['ci'][1]) if c['ci'][1] is not None else 'n/a'}] "
                 f"p={('%.3f' % c['p']) if c['p'] is not None else 'n/a'}")

    emit()
    emit("=" * 78)
    emit("数据质量校验")
    emit("=" * 78)
    ok = [r for r in recs if not r["metrics"].get("error")]
    n_usage = sum(1 for r in ok if r["metrics"].get("usage_present"))
    emit(f"  总轮次 {len(recs)}，无错误 {len(ok)}，有错误 {len(recs) - len(ok)}")
    emit(f"  流式 usage 返回率：{n_usage}/{len(ok)}"
         f" ({100.0 * n_usage / max(len(ok), 1):.1f}%)"
         + ("" if n_usage == len(ok) else "   ← 低于 100% 说明 TPS 退化为按 chunk 估算"))
    tot_tok = sum(r["metrics"].get("total_tokens", 0) for r in ok)
    tot_out = sum(r["metrics"].get("out_tokens", 0) for r in ok)
    tot_think = sum(r["metrics"].get("think_tokens", 0) for r in ok)
    wall = sum(r["metrics"].get("duration_s", 0.0) for r in ok)
    out["data_quality"] = {
        "turns": len(recs), "turns_ok": len(ok), "turns_err": len(recs) - len(ok),
        "usage_present_rate": (n_usage / len(ok)) if ok else 0.0,
        "total_tokens": tot_tok, "out_tokens": tot_out, "think_tokens": tot_think,
        "model_wall_s": wall,
    }
    emit(f"  消耗 token：合计 {tot_tok}（正文 {tot_out} + 思维链 {tot_think}）"
         f"，模型侧总墙钟 {wall / 3600:.2f} 小时")
    err_by_arm = defaultdict(int)
    for r in recs:
        if r["metrics"].get("error"):
            err_by_arm[r["arm"]] += 1
    if err_by_arm:
        emit(f"  各臂错误数：{dict(err_by_arm)}")
        for r in recs:
            if r["metrics"].get("error"):
                emit(f"    例：[{r['arm']}] {r['session_id']} {r['kind']} -> {r['metrics']['error'][:120]}")
                break

    emit()
    emit("=" * 78)
    emit("运行时序特征 (各臂实际生成吞吐)")
    emit("=" * 78)
    tps_by_arm = defaultdict(list)
    dur_by_arm = defaultdict(list)
    for r in recs:
        if r["metrics"].get("error"):
            continue
        tps_by_arm[r["arm"]].append(r["metrics"]["tps"])
        dur_by_arm[r["arm"]].append(r["metrics"]["duration_s"])
    out["runtime"] = {}
    for arm in sorted(tps_by_arm):
        t = tps_by_arm[arm]
        d = dur_by_arm[arm]
        out["runtime"][arm] = {"n": len(t), "median_tps": _safe(st.median, t),
                                "p10_tps": _safe(lambda v: sorted(v)[int(0.1 * len(v))], t),
                                "p90_tps": _safe(lambda v: sorted(v)[int(0.9 * len(v))], t),
                                "median_duration_s": _safe(st.median, d),
                                "median_out_tokens": _safe(st.median, [r["metrics"]["out_tokens"] for r in recs
                                                                     if r["arm"] == arm and not r["metrics"].get("error")])}
        emit(f"  {arm:<14} n={len(t):<4} median tps={_safe(st.median,t):6.1f} "
             f"[p10={_safe(lambda v: sorted(v)[int(0.1*len(v))],t):5.1f}, "
             f"p90={_safe(lambda v: sorted(v)[int(0.9*len(v))],t):5.1f}] "
             f"median duration={_safe(st.median,d):6.2f}s "
             f"median out tokens={_safe(st.median,[r['metrics']['out_tokens'] for r in recs if r['arm']==arm and not r['metrics'].get('error')]):6.0f}")

    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(OUT, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nwrote {OUT}\\summary.json / summary.txt")


if __name__ == "__main__":
    main()
