# -*- coding: utf-8 -*-
"""本地时间感实验的分析：pre（事前剂量-反应）/ posthoc（事后预估）/ process（过程时间感）。

统计口径与上一轮一致：bootstrap CI + 置换检验 + Spearman + log-log 剂量-反应斜率。
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics as st
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

RNG = np.random.default_rng(20261105)


def load(path):
    recs = []
    if not os.path.exists(path):
        return recs
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def spearman(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = ~(np.isnan(a) | np.isnan(b))
    a, b = a[ok], b[ok]
    if len(a) < 3:
        return None
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def bootstrap_ci(x, n_boot=4000, stat=None):
    """stat 要能吃 axis 参数，所以默认用 numpy.median。"""
    stat = stat or np.median
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return (None, None)
    idx = RNG.integers(0, len(x), size=(n_boot, len(x)))
    vals = stat(x[idx], axis=1)
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


def perm_test(a, b, n_perm=20000, stat=None):
    """a vs b 的单侧检验（H1: stat(a) < stat(b)，即 a 的误差更小）。"""
    stat = stat or np.median
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) < 2 or len(b) < 2:
        return None, None
    obs = stat(a) - stat(b)
    pool = np.concatenate([a, b])
    na = len(a)
    diffs = np.empty(n_perm)
    for i in range(n_perm):
        RNG.shuffle(pool)
        diffs[i] = stat(pool[:na]) - stat(pool[na:])
    p = float((np.sum(diffs <= obs) + 1) / (n_perm + 1))
    return float(obs), p


def loglog_slope(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = (x > 0) & (y > 0)
    x, y = x[ok], y[ok]
    if len(x) < 3:
        return None
    return float(np.polyfit(np.log(x), np.log(y), 1)[0])


# ==========================================================================
# pre
# ==========================================================================
def rate_quotes(text: str, limit: int = 3) -> list[str]:
    """从思维链里挑出「模型自己怎么用速率/时间算」的句子。

    这是最硬的证据：不是看数字动了，而是看它**在推理时怎么算的**。
    """
    if not text:
        return []
    sents = re.split(r"[。\n；;]", text)
    keys = ("token", "秒", "速率", "速度", "tokens")
    out = []
    for s in sents:
        s = s.strip()
        if 8 < len(s) < 160 and sum(k in s for k in keys) >= 2:
            out.append(s)
    return out[:limit]


def analyze_pre():
    recs = load(os.path.join(RAW, "local_pre.jsonl"))
    if not recs:
        return None
    arms = {}
    quotes = []
    for r in recs:
        est = r.get("est_s")
        act = r["metrics"]["gen_s"]
        if est is None or est <= 0 or act <= 0:
            continue
        arms.setdefault(r["arm"], []).append({
            "rep": r["rep"], "est": est, "actual": act,
            "log_err": abs(math.log(est / act)),
            "ratio": est / act,
            "rate": r.get("injected_rate"),
            "tps": r["metrics"]["tps"],
            "think": r["metrics"]["think_tokens"],
        })
        if len(quotes) < 12:
            for q in rate_quotes(r["metrics"].get("reasoning") or ""):
                quotes.append({"arm": r["arm"], "rep": r["rep"], "quote": q})
    out = {"n_records": len(recs), "arms": {}, "reasoning_quotes": quotes}
    for arm, rows in arms.items():
        errs = [x["log_err"] for x in rows]
        ests = [x["est"] for x in rows]
        acts = [x["actual"] for x in rows]
        out["arms"][arm] = {
            "n": len(rows),
            "median_log_err": st.median(errs),
            "ci_log_err": bootstrap_ci(errs),
            "median_est": st.median(ests),
            "median_actual": st.median(acts),
            "median_ratio": st.median([x["ratio"] for x in rows]),
            "injected_rate": rows[0].get("rate"),
            "actual_tps_median": st.median([x["tps"] for x in rows]),
        }
    base = arms.get("base")
    if base:
        b_err = [x["log_err"] for x in base]
        for arm, rows in arms.items():
            if arm == "base":
                continue
            d, p = perm_test([x["log_err"] for x in rows], b_err)
            out["arms"][arm]["vs_base_delta_logerr"] = d
            out["arms"][arm]["vs_base_p"] = p
    # 剂量-反应
    doses = [(rows[0].get("rate"), st.median([x["est"] for x in rows]))
             for arm, rows in arms.items() if rows and rows[0].get("rate")]
    doses.sort()
    if len(doses) >= 3:
        out["dose"] = {
            "doses": [{"rate": r, "median_est": e} for r, e in doses],
            "spearman_rate_vs_est": spearman([r for r, _ in doses], [e for _, e in doses]),
            "loglog_slope": loglog_slope([r for r, _ in doses], [e for _, e in doses]),
        }
    return out


# ==========================================================================
# posthoc
# ==========================================================================
def analyze_posthoc():
    recs = load(os.path.join(RAW, "local_posthoc.jsonl"))
    if not recs:
        return None
    arms = {}
    for r in recs:
        est = r.get("est_s")
        act = r["write_metrics"]["gen_s"]
        if est is None or est <= 0 or act <= 0:
            continue
        etok = r.get("est_tokens")
        real_tok = r["write_metrics"]["out_tokens"]
        arms.setdefault(r["arm"], []).append({
            "rep": r["rep"], "est": est, "actual": act,
            "log_err": abs(math.log(est / act)),
            "ratio": est / act,
            "words": r.get("requested_words"),
            "est_tokens": etok, "real_tokens": real_tok,
            "token_ratio": (etok / real_tok) if (etok and real_tok) else None,
            "implied_rate": (etok / est) if (etok and est) else None,
            "write_tokens": r["write_metrics"]["out_tokens"],
            "write_tps": r["write_metrics"]["tps"],
            "think": r["write_metrics"]["think_tokens"],
        })
    out = {"n_records": len(recs), "arms": {}}
    for arm, rows in arms.items():
        errs = [x["log_err"] for x in rows]
        tk = [x["token_ratio"] for x in rows if x.get("token_ratio")]
        ir = [x["implied_rate"] for x in rows if x.get("implied_rate")]
        out["arms"][arm] = {
            "n": len(rows),
            "median_log_err": st.median(errs),
            "ci_log_err": bootstrap_ci(errs),
            "median_est": st.median([x["est"] for x in rows]),
            "median_actual": st.median([x["actual"] for x in rows]),
            "median_ratio": st.median([x["ratio"] for x in rows]),
            "actual_tps_median": st.median([x["write_tps"] for x in rows]),
            "spearman_est_vs_actual": spearman([x["est"] for x in rows], [x["actual"] for x in rows]),
            "median_token_ratio_est_over_real": st.median(tk) if tk else None,
            "median_implied_rate": st.median(ir) if ir else None,
            "rows": [{k: v for k, v in x.items()} for x in rows],
        }
    base = arms.get("base")
    if base:
        b_err = [x["log_err"] for x in base]
        for arm, rows in arms.items():
            if arm == "base":
                continue
            d, p = perm_test([x["log_err"] for x in rows], b_err)
            out["arms"][arm]["vs_base_delta_logerr"] = d
            out["arms"][arm]["vs_base_p"] = p
    return out


# ==========================================================================
# process
# ==========================================================================
# 注意：本地模型会把标记写成「〔已用时 15〕」（**不带「秒」字**），
# 所以「秒」必须可选，否则会把合规输出整段判成 0 个标记。
MARK_RE = re.compile(r"[（(〔【]\s*已用时\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:秒)?\s*[)）〕】]")


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


def marker_true_times(rec):
    """把每个标记定位到流里的真实经过秒数。

    做法：content 里标记的字符偏移 → 落在哪个 chunk（按累计正文字符数定位）
    → 该 chunk 的到达时刻。chunk 时刻相对 t_request 存储，所以：
        真实流逝（从开始生成算起） = chunk_time - ttft
    思维链阶段的时间也在同一条流里，因此自然被算进去——这正是「长思考」的误差来源。
    """
    m = rec["metrics"]
    times = m.get("chunk_times") or []
    cc = m.get("chunk_content_chars") or []
    ttft = m.get("ttft_s")
    if not times or not cc or ttft is None:
        return []
    content = m.get("content") or ""
    marks = []
    for mo in MARK_RE.finditer(content):
        p = mo.start()
        cum = 0
        hit = None
        for j, n in enumerate(cc):
            cum += n
            if cum > p:
                hit = j
                break
        if hit is None:
            hit = len(cc) - 1
        t_rel_req = times[min(hit, len(times) - 1)]
        marks.append({
            "marked": float(mo.group(1)),
            "true_elapsed": round(t_rel_req - ttft, 3),      # 从「开始生成」算起
            "true_from_request": round(t_rel_req, 3),        # 从「发出请求」算起
            "chunk": hit,
        })
    return marks


def analyze_process(fname: str = "local_process.jsonl"):
    recs = load(os.path.join(RAW, fname))
    if not recs:
        return None
    arms = {}
    for r in recs:
        m = r["metrics"]
        marks = marker_true_times(r)
        if not marks:
            arms.setdefault(r["arm"], []).append({
                "rep": r["rep"], "n_marks": 0, "gen_s": m["gen_s"],
                "think_tokens": m["think_tokens"], "content_tokens": m["content_tokens"],
                "think_end_s": m.get("think_end_s"), "within_spearman": None,
                "last_marked": None, "last_true": None, "last_ratio": None,
                "within_mean_abs_log": None, "marks": [],
            })
            continue
        tv = [x["true_elapsed"] for x in marks]
        mv = [x["marked"] for x in marks]
        ratios = [x["marked"] / x["true_elapsed"] for x in marks
                  if x["true_elapsed"] > 0 and x["marked"] > 0]
        abslog = [abs(math.log(x["marked"] / x["true_elapsed"])) for x in marks
                  if x["true_elapsed"] > 0 and x["marked"] > 0]
        slope, inter, r2 = ols(tv, mv)
        arms.setdefault(r["arm"], []).append({
            "rep": r["rep"], "n_marks": len(marks),
            "gen_s": m["gen_s"], "think_tokens": m["think_tokens"],
            "content_tokens": m["content_tokens"], "think_end_s": m.get("think_end_s"),
            "within_spearman": spearman(tv, mv),
            "last_marked": mv[-1], "last_true": tv[-1],
            "last_ratio": mv[-1] / tv[-1] if tv[-1] else None,
            "within_mean_abs_log": st.median(abslog) if abslog else None,
            "slope": slope, "intercept": inter, "r2": r2,
            "think_share_of_time": ((m.get("think_end_s") or 0) - (m.get("ttft_s") or 0))
                                   / max(m["gen_s"], 1e-6),
            "marks": marks,
        })
    out = {"n_records": len(recs), "arms": {}}
    for arm, rows in arms.items():
        last_ratios = [x["last_ratio"] for x in rows if x["last_ratio"]]
        within = [x["within_spearman"] for x in rows if x["within_spearman"] is not None]
        out["arms"][arm] = {
            "n": len(rows),
            "n_marks_median": st.median([x["n_marks"] for x in rows]),
            "zero_mark_runs": sum(1 for x in rows if x["n_marks"] == 0),
            "median_gen_s": st.median([x["gen_s"] for x in rows]),
            "median_think_tokens": st.median([x["think_tokens"] for x in rows]),
            "median_think_share_of_time": st.median(
                [x.get("think_share_of_time") or 0 for x in rows]),
            "median_last_ratio": st.median(last_ratios) if last_ratios else None,
            "ci_last_ratio": bootstrap_ci(last_ratios) if len(last_ratios) > 1 else (None, None),
            "median_within_spearman": st.median(within) if within else None,
            "within_spearman_list": within,
            "median_within_abs_log": st.median(
                [x["within_mean_abs_log"] for x in rows if x["within_mean_abs_log"] is not None]),
            "median_slope": st.median([x["slope"] for x in rows if x.get("slope") is not None])
            if any(x.get("slope") is not None for x in rows) else None,
            "median_intercept": st.median([x["intercept"] for x in rows if x.get("intercept") is not None])
            if any(x.get("intercept") is not None for x in rows) else None,
            "median_r2": st.median([x["r2"] for x in rows if x.get("r2") is not None])
            if any(x.get("r2") is not None for x in rows) else None,
            "cross_run_spearman_gen_vs_lastmark": spearman(
                [x["gen_s"] for x in rows if x["last_marked"]],
                [x["last_marked"] for x in rows if x["last_marked"]]),
        }
    return out


# ==========================================================================
# 预先定好的成功判据（在看数据之前定，避免事后找说法）
# ==========================================================================
CRITERIA = {
    "C1_稳定性前提": {
        "条件": "热态 TPS max/min ≤ 1.30 且 请求间 CV ≤ 0.15",
        "对照": "MiniMax API: max/min 2.39×, 请求间 CV 0.920",
        "判据来源": "local_tps_summary.json",
    },
    "C2_剂量反应": {
        "条件": "注入速率与预估值显著负相关（Spearman < 0），且 log-log 斜率 b 明显远离 0",
        "含义": "说明「速率」这个数真的进了模型的判断（而不是被忽略）",
    },
    "C3_粗略时间感": {
        "条件": "注入真实速率后，跨轮 Spearman(预估, 真实耗时) ≥ 0.5，或相对基线的对数误差显著下降（p < 0.05）",
        "口径": "用户口径：时间感只需要大概的就行",
    },
    "C4_长思考过程时间感": {
        "条件": "同一轮内 Spearman(真实流逝, 标记值) ≥ 0.5，且末标记/真实总耗时落在 0.5–2.0",
        "含义": "模型在长思考里能边写边报出大致正确的时间",
    },
}


def analyze_process2():
    """两段式（思考 → 时钟注入 → 写正文）。

    关键：标记的真实时刻 = **思考段耗时** + 正文段内流逝。
    只看正文段会低估「从开始生成算起」的真实时间。
    """
    recs = load(os.path.join(RAW, "local_process2.jsonl"))
    if not recs:
        return None
    arms = {}
    for r in recs:
        m = r["metrics"]
        think_s = r.get("think_s") or 0.0
        times = m.get("chunk_times") or []
        cc = m.get("chunk_content_chars") or []
        ttft = m.get("ttft_s")
        content = m.get("content") or ""
        marks = []
        if times and cc and ttft is not None:
            for mo in MARK_RE.finditer(content):
                p = mo.start()
                cum, hit = 0, None
                for j, n in enumerate(cc):
                    cum += n
                    if cum > p:
                        hit = j
                        break
                if hit is None:
                    hit = len(cc) - 1
                t_rel = times[min(hit, len(times) - 1)]
                marks.append({
                    "marked": float(mo.group(1)),
                    "true_elapsed": round(think_s + (t_rel - ttft), 3),   # 含思考段
                    "true_write_only": round(t_rel - ttft, 3),
                })
        total_true = think_s + (m.get("gen_s") or 0.0)
        tv = [x["true_elapsed"] for x in marks]
        mv = [x["marked"] for x in marks]
        rows = {
            "rep": r["rep"], "n_marks": len(marks),
            "think_s": think_s, "write_s": m.get("gen_s"), "total_true": total_true,
            "within_spearman": spearman(tv, mv),
            "last_marked": mv[-1] if mv else None,
            "last_true": tv[-1] if tv else None,
            "last_ratio": (mv[-1] / tv[-1]) if (mv and tv and tv[-1]) else None,
            "marks": marks,
        }
        arms.setdefault(r["arm"], []).append(rows)
    out = {"n_records": len(recs), "arms": {}}
    for arm, rows in arms.items():
        lr = [x["last_ratio"] for x in rows if x["last_ratio"]]
        within = [x["within_spearman"] for x in rows if x["within_spearman"] is not None]
        out["arms"][arm] = {
            "n": len(rows),
            "n_marks_median": st.median([x["n_marks"] for x in rows]),
            "zero_mark_runs": sum(1 for x in rows if x["n_marks"] == 0),
            "median_think_s": st.median([x["think_s"] for x in rows]),
            "median_total_true_s": st.median([x["total_true"] for x in rows]),
            "median_last_ratio": st.median(lr) if lr else None,
            "ci_last_ratio": bootstrap_ci(lr) if len(lr) > 1 else (None, None),
            "median_within_spearman": st.median(within) if within else None,
            "within_spearman_list": within,
            "rows": rows,
        }
    return out


def evaluate_criteria(summary: dict, tps: dict) -> dict:
    verdict = {}
    if tps:
        w = tps.get("steady") or tps.get("warm") or {}
        ok = (w.get("max_over_min") is not None and w["max_over_min"] <= 1.30
              and w.get("between_cv") is not None and w["between_cv"] <= 0.15)
        verdict["C1_稳定性前提"] = {
            "pass": bool(ok),
            "tier": "steady（排除加载后前两次预热）",
            "n": w.get("n"),
            "steady_max_over_min": w.get("max_over_min"),
            "steady_between_cv": w.get("between_cv"),
            "steady_median": w.get("median"),
            "cold_first_run_tps": (tps.get("warm") or {}).get("cold_first_run_tps"),
            "all_runs_max_over_min": (tps.get("merged") or {}).get("max_over_min"),
        }
    pre = (summary.get("pre") or {})
    dose = pre.get("dose") or {}
    sp = dose.get("spearman_rate_vs_est")
    b = dose.get("loglog_slope")
    if sp is not None:
        verdict["C2_剂量反应"] = {
            "pass": bool(sp < 0 and b is not None and b < -0.15),
            "spearman_rate_vs_est": sp, "loglog_slope": b,
        }
    post = (summary.get("posthoc") or {})
    sp_arm = None
    for arm in ("speed", "elapsed"):
        a = (post.get("arms") or {}).get(arm) or {}
        if a.get("spearman_est_vs_actual") is not None:
            sp_arm = max(sp_arm or 0, a["spearman_est_vs_actual"])
    if sp_arm is not None:
        base = (post.get("arms") or {}).get("base") or {}
        p_best = min([((post.get("arms") or {}).get(a) or {}).get("vs_base_p", 1)
                      for a in ("speed", "elapsed")], default=1)
        verdict["C3_粗略时间感"] = {
            "pass": bool(sp_arm >= 0.5 or p_best < 0.05),
            "best_spearman_est_vs_actual": sp_arm,
            "best_vs_base_p": p_best,
            "base_median_log_err": base.get("median_log_err"),
        }
    proc = (summary.get("process") or {})
    arms = proc.get("arms") or {}
    # 优化臂（速率 + 工作单元换算）也参与 C4 判定
    for arm, a in ((summary.get("process_opt") or {}).get("arms") or {}).items():
        arms[f"opt:{arm}"] = a
    best_arm, best_sp, best_ratio = None, None, None
    for arm, a in arms.items():
        sp = a.get("median_within_spearman")
        ratio = a.get("median_last_ratio")
        if sp is not None and (best_sp is None or sp > best_sp):
            best_arm, best_sp, best_ratio = arm, sp, ratio
    # 「最准」要同时看误差倍数和斜率：只看轮内相关会被「完美等差数列」骗到
    cand = [(a.get("median_last_ratio"), a.get("median_slope"), arm)
            for arm, a in arms.items()
            if a.get("median_last_ratio") and a.get("median_slope")]
    best_fit = min(cand, key=lambda x: abs(math.log(max(x[0], 1e-6))) + abs(math.log(max(x[1], 1e-6)))
                   ) if cand else None
    if best_fit:
        ratio, slope, arm = best_fit
        ok = 0.5 <= ratio <= 2.0 and 0.5 <= slope <= 1.6
        verdict["C4_长思考过程时间感"] = {
            "pass": bool(ok),
            "best_arm": arm,
            "best_last_ratio": ratio, "best_slope": slope,
            "best_within_spearman": best_sp,
            "note": "同时看倍数与斜率：只看轮内相关会被「完美等差数列」骗到"
                    "（未加单元换算时轮内相关也 = 1.0，但斜率 16–22）",
            "per_arm": {k: {"within_spearman": v.get("median_within_spearman"),
                            "last_ratio": v.get("median_last_ratio"),
                            "slope": v.get("median_slope"),
                            "intercept": v.get("median_intercept"),
                            "n_marks_median": v.get("n_marks_median")}
                        for k, v in arms.items()},
        }
    return verdict


def main():
    os.makedirs(OUT, exist_ok=True)
    summary = {}
    for name, fn in (("pre", analyze_pre), ("posthoc", analyze_posthoc),
                     ("process", analyze_process),
                     ("process_opt", lambda: analyze_process("local_process_opt.jsonl")),
                     ("process2", analyze_process2)):
        a = fn()
        if a:
            summary[name] = a
            with open(os.path.join(OUT, f"local_{name}_summary.json"), "w",
                      encoding="utf-8") as f:
                json.dump(a, f, ensure_ascii=False, indent=1)
    if not summary:
        print("没有可分析的本地实验数据")
        return
    tps = None
    tp = os.path.join(OUT, "local_tps_summary.json")
    if os.path.exists(tp):
        tps = json.load(open(tp, encoding="utf-8"))
    summary["criteria"] = CRITERIA
    summary["verdict"] = evaluate_criteria(summary, tps)
    with open(os.path.join(OUT, "local_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("判据结果：")
    print(json.dumps(summary["verdict"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
