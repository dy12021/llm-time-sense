# -*- coding: utf-8 -*-
"""TPS 标定分析：稳定速率是多少，波动到底来自哪里。

回答
----
1. 串行真的成立吗？        -> 断言所有请求区间互不重叠。
2. 30 秒生成过程中速率平稳吗？ -> 滑动窗口 TPS（正文 / 总量分开）。
3. 时长的方差来自哪里？    -> 把 duration 拆成
       duration = ttft + (content_tokens + think_tokens) / rate
   分母 rate（服务端速率）稳不稳？分子 think_tokens（思维链产量）稳不稳？
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")


def load(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return recs


def pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(int(q * len(s)), len(s) - 1)]


def cv(xs):
    if len(xs) < 2 or sum(xs) == 0:
        return None
    return st.pstdev(xs) / (sum(xs) / len(xs))


def linfit(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    return {"a": a, "b": b, "r2": (1 - ss_res / ss_tot) if ss_tot > 0 else None, "n": n}


def chunk_offsets(m):
    gaps = m.get("chunk_gaps") or []
    first = m.get("first_chunk_s")
    if not gaps or first is None:
        return None, None
    ts = [first]
    for g in gaps:
        ts.append(ts[-1] + g)
    return ts, m.get("last_chunk_s")


def window_tps(rec, win_s, which="content"):
    m = rec["metrics"]
    ts, last = chunk_offsets(m)
    if ts is None or last is None:
        return []
    if which == "content":
        chars = m.get("chunk_content_chars") or []
        tok_total = m.get("content_tokens") or 0
    else:
        chars = m.get("chunk_chars") or []
        tok_total = m.get("out_tokens") or 0
    if not chars or tok_total <= 0:
        return []
    total_c = sum(chars)
    if total_c <= 0:
        return []
    scale = tok_total / total_c
    out = []
    span = last - ts[0]
    if span <= 0:
        return []
    t = 0.0
    while t + win_s <= span + 1e-9:
        c = sum(ch for ch, tt in zip(chars, ts) if t <= tt < t + win_s)
        out.append({"t_start": round(ts[0] + t, 3), "tps": (c * scale) / win_s})
        t += win_s / 2.0
    return out


def serial_check(recs):
    ivs = sorted([(r["metrics"]["t_request"], r["metrics"]["t_last"], r.get("rep")) for r in recs],
                 key=lambda x: x[0])
    overlaps = []
    for i in range(len(ivs) - 1):
        if ivs[i][1] > ivs[i + 1][0] + 1e-6:
            overlaps.append((ivs[i], ivs[i + 1]))
    gaps = [ivs[i + 1][0] - ivs[i][1] for i in range(len(ivs) - 1)]
    return len(ivs), len(overlaps), (min(gaps) if gaps else None), (st.median(gaps) if gaps else None)


def analyze_set(recs, title):
    print()
    print("#" * 74)
    print(f"# {title}   (n={len(recs)})")
    print("#" * 74)
    ok = [r for r in recs if not r["metrics"].get("error")]
    trunc = [r for r in ok if r["metrics"].get("finish_reason") == "length"]
    clean = [r for r in ok if r["metrics"].get("finish_reason") != "length"]
    out = {"n": len(recs), "n_ok": len(ok), "n_truncated": len(trunc)}

    print(f"  截断（撞 max_completion_tokens）：{len(trunc)}/{len(ok)}"
          f"{'  <- 截断样本不参与速率统计' if trunc else ''}")
    out["truncated"] = len(trunc)

    if not clean:
        return out

    # ---- per-run table
    print()
    print(f"  {'rep':>4}{'dur(s)':>9}{'gen(s)':>9}{'ttft':>7}{'out':>7}{'think':>7}"
          f"{'content':>9}{'tps_all':>9}{'tps_txt':>9}{'finish':>9}")
    for r in clean:
        m = r["metrics"]
        print(f"  {r.get('rep',0):>4}{m['duration_s']:>9.2f}{m['gen_s']:>9.2f}"
              f"{(m['ttft_s'] or 0):>7.2f}{m['out_tokens']:>7}{m['think_tokens']:>7}"
              f"{m['content_tokens']:>9}"
              f"{m['tps']:>9.1f}{m['content_tokens']/max(m['gen_s'],1e-9):>9.1f}"
              f"{str(m.get('finish_reason')):>9}")

    tps_all = [r["metrics"]["out_tokens"] / max(r["metrics"]["gen_s"], 1e-6) for r in clean]
    tps_txt = [r["metrics"]["content_tokens"] / max(r["metrics"]["gen_s"], 1e-6) for r in clean]
    think = [r["metrics"]["think_tokens"] for r in clean]
    content = [r["metrics"]["content_tokens"] for r in clean]
    dur = [r["metrics"]["duration_s"] for r in clean]

    print()
    print(f"  总吞吐 TPS ：median={st.median(tps_all):6.1f}  p10={pct(tps_all,.1):6.1f}  "
          f"p90={pct(tps_all,.9):6.1f}  max/min={max(tps_all)/min(tps_all):.2f}x  CV={cv(tps_all):.3f}")
    print(f"  正文吞吐 TPS：median={st.median(tps_txt):6.1f}  p10={pct(tps_txt,.1):6.1f}  "
          f"p90={pct(tps_txt,.9):6.1f}  max/min={max(tps_txt)/min(tps_txt):.2f}x  CV={cv(tps_txt):.3f}")
    print(f"  思维链 token：median={st.median(think):7.0f}  min={min(think):6.0f}  "
          f"max={max(think):6.0f}  max/min={(max(think)/max(min(think),1)):.1f}x")
    print(f"  正文 token  ：median={st.median(content):7.0f}  min={min(content):6.0f}  "
          f"max={max(content):6.0f}  max/min={max(content)/max(min(content),1):.2f}x")
    print(f"  总时长      ：median={st.median(dur):6.2f}s  min={min(dur):6.2f}  max={max(dur):6.2f}  "
          f"max/min={max(dur)/min(dur):.2f}x")
    out.update({"tps_all": tps_all, "tps_text": tps_txt, "think": think,
                "content": content, "duration": dur,
                "median_tps_text": st.median(tps_txt), "median_tps_all": st.median(tps_all),
                "cv_tps_text": cv(tps_txt), "cv_tps_all": cv(tps_all),
                "think_ratio": (max(think) / max(min(think), 1)),
                "content_ratio": (max(content) / max(min(content), 1)),
                "dur_ratio": (max(dur) / min(dur))})

    # ---- windowed rate
    print()
    print("  滑动窗口速率（同一段生成内部）")
    for win in (5.0, 10.0):
        for which, tag in (("content", "正文"), ("all", "总量")):
            vals = []
            for r in clean:
                vals.extend(w["tps"] for w in window_tps(r, win, which))
            if not vals:
                continue
            print(f"    窗口 {win:>4.0f}s [{tag}] n={len(vals):>4} median={st.median(vals):6.1f} "
                  f"p10={pct(vals,.1):6.1f} p90={pct(vals,.9):6.1f} CV={cv(vals):.3f}")
            out[f"win{win}_{which}"] = {"n": len(vals), "median": st.median(vals),
                                        "p10": pct(vals, .1), "p90": pct(vals, .9), "cv": cv(vals),
                                        "values": vals}

    # ---- variance attribution: how much of duration variance is thinking?
    if len(clean) >= 3:
        med_rate = st.median(tps_txt)
        print()
        print(f"  方差归因（以正文速率中位数 {med_rate:.1f} token/s 为基准）")
        pred = [(m["content_tokens"] + m["think_tokens"]) / med_rate for m in
                (r["metrics"] for r in clean)]
        obs = [r["metrics"]["duration_s"] for r in clean]
        # correlation between thinking volume and duration
        if len(set(think)) > 1:
            def pearson(a, b):
                ma, mb = sum(a) / len(a), sum(b) / len(b)
                num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
                da = sum((x - ma) ** 2 for x in a) ** 0.5
                db = sum((y - mb) ** 2 for y in b) ** 0.5
                return num / (da * db) if da and db else None
            r_think = pearson(think, obs)
            r_content = pearson(content, obs)
            print(f"    corr(思维链 token, 总时长) = {r_think:+.3f}")
            print(f"    corr(正文 token,   总时长) = {r_content:+.3f}")
            out["corr_think_duration"] = r_think
            out["corr_content_duration"] = r_content
            think_share = [m["think_tokens"] / max(m["out_tokens"], 1) for m in
                           (r["metrics"] for r in clean)]
            print(f"    思维链占总输出比例：median={st.median(think_share):.1%} "
                  f"max={max(think_share):.1%}")
            out["think_share_median"] = st.median(think_share)
            out["think_share_max"] = max(think_share)
    return out


def main():
    files = sys.argv[1:] or [os.path.join(RAW, "tps_long_items.jsonl")]
    all_out = {}
    for f in files:
        recs = load(f)
        if not recs:
            print(f"(skip empty {f})")
            continue
        print()
        print("=" * 74)
        print(f"FILE: {f}")
        print("=" * 74)
        n, ov, gmin, gmed = serial_check(recs)
        print(f"  串行性：{n} 次调用，重叠 {ov} 次 -> "
              f"{'串行成立 ✓' if ov == 0 else '存在并发 ✗'}"
              f"（相邻间隔 min={gmin} median={gmed}）")
        all_out[os.path.basename(f)] = {
            "serial": {"n": n, "overlaps": ov, "min_gap": gmin, "median_gap": gmed},
            **analyze_set(recs, os.path.basename(f)),
        }

    # cross-file comparison
    print()
    print("=" * 74)
    print("汇总：波动到底来自哪里")
    print("=" * 74)
    print(f"  {'数据集':<26}{'正文TPS中位':>12}{'正文CV':>9}{'总CV':>9}{'思维链max/min':>14}")
    for k, v in all_out.items():
        if "median_tps_text" not in v:
            continue
        print(f"  {k:<26}{v['median_tps_text']:>12.1f}{v['cv_tps_text']:>9.3f}"
              f"{v['cv_tps_all']:>9.3f}{v['think_ratio']:>13.1f}x")
    print()
    print("  读法：正文 TPS 的 CV 小 => 服务端速率是稳的；")
    print("        思维链 max/min 大 => 每次要吐多少思维链不可预测，")
    print("        而它直接乘在时长上 => 时长的方差主要来自模型自己，而不是服务端。")

    with open(os.path.join(OUT, "tps_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(all_out, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nwrote {OUT}\\tps_analysis.json")


if __name__ == "__main__":
    main()
