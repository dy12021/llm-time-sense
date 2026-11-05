# -*- coding: utf-8 -*-
"""Phase B — 用标定好的 TPS 做 30 秒实验。**每次实验清空上下文**，全程串行。

与第一轮实验的差别
------------------
第一轮（450 轮）里，「报出上一条回复用时」的问句紧跟在模型自己的预估轮之后，
模型复读自己上轮的预测（污染）。这里**每次实验都是全新会话**，只有一条用户消息，
因此模型无从复读，只能真的去算。

四臂
----
base        无任何反馈
speed_cal   注入标定得到的稳定 TPS（中位数）
speed_range 注入标定得到的 TPS **中位数 + 不确定度区间**
elapsed     注入绝对时间量（阳性对照）

两类题目
--------
A. 写满 N 秒：要求模型写出生成耗时约 N 秒的内容，并先给出自己的耗时预估。
   -> 命中误差 + 预估误差
B. 纯换算：给一段确定的 token 量，问用实测速度需要多少秒。
   -> 速率信号到底有没有被用起来
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.client import LLMClient, load_llm_config  # noqa: E402
from harness import tasks as T  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

ARMS = ["base", "speed_cal", "speed_range", "elapsed"]

TOPICS = [
    "城市与海洋", "候鸟的迁徙", "森林的水循环", "深海的热泉",
    "季风与农业", "候车的陌生人", "古树的年轮", "潮汐与港口",
]


def load_calibration(prefer: str = "") -> dict:
    """Read the calibration produced by analyze_tps.py and POOL all datasets.

    Pooling gives the most defensible constant (and the widest honest range):
    the deployment turns out to be bimodal, so any single number is an
    approximation with a big error bar.
    """
    p = os.path.join(OUT, "tps_analysis.json")
    if not os.path.exists(p):
        raise SystemExit(f"缺少标定结果：{p}（先跑 analyze_tps.py）")
    d = json.load(open(p, encoding="utf-8"))
    vals, srcs = [], []
    for name, v in d.items():
        if "tps_text" not in v or not v.get("tps_text"):
            continue
        if prefer and prefer not in name:
            continue
        vals.extend(v["tps_text"])
        srcs.append(name)
    if not vals:
        raise SystemExit(f"标定结果里没有可用的速率：{p}")
    vals = sorted(vals)
    n = len(vals)
    return {
        "source": "+".join(srcs),
        "median": vals[n // 2],
        "p10": vals[int(0.10 * n)],
        "p90": vals[min(int(0.90 * n), n - 1)],
        "min": vals[0],
        "max": vals[-1],
        "n_runs": n,
        "ratio": vals[-1] / max(vals[0], 1e-9),
    }


def build_system(arm: str, cal: dict, elapsed_hint: float) -> str:
    if arm == "base":
        return T.SYSTEM_BASE
    if arm == "speed_cal":
        return (T.SYSTEM_BASE + "\n\n## 运行反馈（外部计时器实测）\n"
                f"- 实测生成速度：约 {cal['median']:.0f} token/秒。")
    if arm == "speed_range":
        return (T.SYSTEM_BASE + "\n\n## 运行反馈（外部计时器实测）\n"
                f"- 实测生成速度：中位数约 {cal['median']:.0f} token/秒，"
                f"实测区间 {cal['p10']:.0f}–{cal['p90']:.0f} token/秒"
                f"（{cal['n_runs']} 次独立测量，速率本身有波动）。")
    if arm == "elapsed":
        return (T.SYSTEM_BASE + "\n\n## 运行反馈（外部计时器实测）\n"
                f"- 刚才那次生成实测耗时 {elapsed_hint:.1f} 秒。")
    raise ValueError(arm)


PROMPT_A = """请写一段内容，使它自己的生成耗时（从开始生成到结束）大约为 {n} 秒。
内容主题：{topic}

请按下面的格式回答，第一行先给出估计，再写正文：
预计耗时：X
（X 是你估计这条回复的生成耗时，秒，取整数）
然后另起一行写出这条回复的正文。正文要足够长，长度由你自己按 {n} 秒的目标来把握。"""

PROMPT_B = """外部计时器实测：你的生成速度约为 {tps:.0f} token/秒。
现在有一段中文内容，共 {tokens} 个 token。
请只回答一个数字：生成这段内容大约需要多少秒？只输出数字，不要解释。"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--trials", type=int, default=8, help="A 题每臂重复次数")
    ap.add_argument("--b-trials", type=int, default=4, help="B 题每臂重复次数")
    ap.add_argument("--target-s", type=int, default=30)
    ap.add_argument("--max-tokens", type=int, default=4000)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--out", default=os.path.join(RAW, "phase_b_30s.jsonl"))
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    cal = load_calibration()
    print(f"标定结果（来源 {cal['source']}）：正文速率中位 {cal['median']:.1f} token/s，"
          f"区间 {cal['p10']:.1f}–{cal['p90']:.1f}，n={cal['n_runs']} 次 30 秒实验，"
          f"max/min={cal['ratio']:.2f}x", flush=True)

    client = LLMClient(load_llm_config())
    records = []
    mode = "w" if args.fresh else "a"
    t0 = time.perf_counter()
    with open(args.out, mode, encoding="utf-8") as out_f:
        for arm in args.arms.split(","):
            # ---------------- task A: write to hit N seconds (fresh ctx) -------
            for k in range(1, args.trials + 1):
                topic = TOPICS[(k - 1) % len(TOPICS)]
                # 给 elapsed 臂一个真实的绝对时间量：取标定中位生成时长
                elapsed_hint = args.target_s
                sysmsg = build_system(arm, cal, elapsed_hint)
                prompt = PROMPT_A.format(n=args.target_s, topic=topic)
                msgs = [{"role": "system", "content": sysmsg},
                        {"role": "user", "content": prompt}]
                m = client.chat(msgs, max_completion_tokens=args.max_tokens,
                                temperature=args.temperature, reasoning_effort=args.effort,
                                arm=arm, task_id=f"A{k}", turn_index=k, capture_chunks=True)
                est = T.parse_seconds(m.content, "预计耗时")
                rec = {"phase": "B_A", "arm": arm, "trial": k, "topic": topic,
                       "target_s": args.target_s, "parsed": {"estimate_s": est},
                       "metrics": m.to_dict(), "ts": time.time()}
                records.append(rec)
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_f.flush()
                print(f"  [{arm:<12}] A{k:<2} est={est} dur={m.duration_s:6.2f}s gen={m.gen_s:6.2f}s "
                      f"out_tok={m.out_tokens:5d} tps={m.tps:6.1f}"
                      + (f"  ERR={m.error[:60]}" if m.error else ""), flush=True)

            # ---------------- task B: pure conversion (fresh ctx) -------------
            for k in range(1, args.b_trials + 1):
                tokens = [500, 1500, 3000, 4500][(k - 1) % 4]
                sysmsg = build_system(arm, cal, args.target_s)
                prompt = PROMPT_B.format(tps=cal["median"], tokens=tokens)
                msgs = [{"role": "system", "content": sysmsg},
                        {"role": "user", "content": prompt}]
                m = client.chat(msgs, max_completion_tokens=400,
                                temperature=args.temperature, reasoning_effort=args.effort,
                                arm=arm, task_id=f"B{k}", turn_index=k)
                est = T.parse_seconds(m.content)
                truth = tokens / cal["median"]
                rec = {"phase": "B_B", "arm": arm, "trial": k, "tokens": tokens,
                       "truth_s": truth, "parsed": {"estimate_s": est},
                       "metrics": m.to_dict(), "ts": time.time()}
                records.append(rec)
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_f.flush()
                print(f"  [{arm:<12}] B{k:<2} {tokens} tok -> 真值 {truth:5.1f}s "
                      f"模型答 {est}", flush=True)

    dt = time.perf_counter() - t0
    print(f"\ndone: {len(records)} trials in {dt/60:.1f} min (严格串行, 每次清空上下文)")


if __name__ == "__main__":
    main()
