# -*- coding: utf-8 -*-
"""Phase A — 30 秒连续生成的 TPS 标定。严格串行，每轮清空上下文。

协议（用户指定）
----------------
1. 每次实验 = **一次连续生成约 30 秒**，统计这 30 秒内的 TPS。
   固定开销（TTFT、尾部交付）在 30 秒窗口里被摊薄，得到的才是「稳定 TPS」。
2. **不保留上下文**：每次实验都是全新会话，只有那一条用户消息，互不影响。
3. **不开并发**：全程单线程单请求；每次调用记录 [t_request, t_last]，
   analyze_tps.py 会断言区间互不重叠，否则判定本次标定被污染。

输出：raw/tps_long.jsonl，每轮含逐块到达时刻与每块字符数，
分析时用滑动窗口换算 TPS（见 analyze_tps.py）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.client import LLMClient, load_llm_config  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")

TOPIC_PROMPTS = [
    ("城市与海洋", "城市与海洋"),
    ("候鸟的迁徙", "候鸟的迁徙"),
    ("森林的水循环", "森林的水循环"),
]


def build_prompt(topic: str, words: int, mode: str) -> str:
    if mode == "items":
        # Deterministic length, minimal chain-of-thought -> clean rate measurement.
        n_items = max(10, int(words / 18))
        return (
            f"请输出恰好 {n_items} 条编号条目，每条一行，每条是一句关于「{topic}」的陈述。"
            f"只输出条目本身，不要标题、不要说明、不要空行。"
        )
    return (
        f"请写一篇**至少 {words} 字**的中文长文，主题是「{topic}」。\n"
        f"要求：必须写满 {words} 字以上才能结束，内容要具体（可举例子、给数据、描述细节），"
        f"不要提前收尾，也不要重复同一句话来凑字数。\n"
        f"只输出文章正文，不要标题、不要说明、不要列表。"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=6, help="30 秒实验的重复次数（每次都清空上下文）")
    ap.add_argument("--words", type=int, default=2000, help="要求的字数（决定生成时长）")
    ap.add_argument("--target-s", type=float, default=30.0, help="目标生成秒数（仅用于自检打印）")
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--mode", default="items", choices=["items", "longform"],
                    help="items=确定性长度(干净速率测量) / longform=长文(会诱发思维链膨胀)")
    ap.add_argument("--out", default=os.path.join(RAW, "tps_long.jsonl"))
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    client = LLMClient(load_llm_config())
    records = []
    mode = "w" if args.fresh else "a"
    t0 = time.perf_counter()

    print(f"协议：单次连续生成≈{args.target_s:.0f}s，每次实验清空上下文，全程串行", flush=True)
    with open(args.out, mode, encoding="utf-8") as out_f:
        for rep in range(1, args.repeats + 1):
            topic, _ = TOPIC_PROMPTS[(rep - 1) % len(TOPIC_PROMPTS)]
            # >>> fresh context every time: exactly one user message <<<
            msgs = [{"role": "user", "content": build_prompt(topic, args.words, args.mode)}]

            m = client.chat(
                msgs,
                max_completion_tokens=args.max_tokens,
                temperature=args.temperature,
                reasoning_effort=args.effort,
                arm=f"tps30_{args.mode}",
                task_id=f"r{rep}",
                turn_index=rep,
                capture_chunks=True,
            )
            rec = {
                "phase": "TPS30", "mode": args.mode, "rep": rep, "topic": topic,
                "words": args.words, "target_s": args.target_s,
                "metrics": m.to_dict(), "ts": time.time(),
            }
            records.append(rec)
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()

            hit = "OK " if abs(m.duration_s - args.target_s) <= 6 else "OFF"
            trunc = "TRUNC" if m.finish_reason == "length" else "     "
            print(f"  [{hit}][{trunc}] rep{rep} dur={m.duration_s:6.2f}s gen={m.gen_s:6.2f}s "
                  f"ttft={m.ttft_s if m.ttft_s is not None else -1:5.2f}s "
                  f"out_tok={m.out_tokens:5d} think={m.think_tokens:4d} content={m.content_tokens:5d} "
                  f"tps={m.tps:6.1f} tps_content={m.content_tokens / max(m.gen_s, 1e-6):6.1f} "
                  f"gap_med={m.gap_median} burst={m.burst_frac} finish={m.finish_reason}",
                  flush=True)
            if m.error:
                print(f"       ERROR: {m.error[:160]}", flush=True)

    dt = time.perf_counter() - t0
    durs = [r["metrics"]["duration_s"] for r in records]
    print(f"\ndone: {len(records)} 次 30 秒实验，串行耗时 {dt/60:.1f} min")
    if durs:
        print(f"实际生成时长：min={min(durs):.1f}s max={max(durs):.1f}s "
              f"mean={sum(durs)/len(durs):.1f}s")


if __name__ == "__main__":
    main()
