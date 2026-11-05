# -*- coding: utf-8 -*-
"""L1 — 本地模型 TPS 稳定性标定（对照 MiniMax API 的 2.39× 抖动）。

协议沿用上一轮（harness/tps_long.py），只换被试与端点：
  1. 每次实验 = 一次连续生成约 30 秒；
  2. 每次实验清空上下文（只有那一条用户消息）；
  3. 全程串行，不开并发；记录 [t_request, t_last] 供分析层断言区间不重叠。

输出：raw/local_tps.jsonl（逐块到达时刻 + 每块字符数 + usage）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from local.lclient import LocalClient  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")

TOPICS = ["城市与海洋", "候鸟的迁徙", "森林的水循环"]


def build_prompt(topic: str, words: int, mode: str) -> str:
    if mode == "items":
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
    ap.add_argument("--repeats", type=int, default=6)
    ap.add_argument("--words", type=int, default=3500)
    ap.add_argument("--target-s", type=float, default=30.0)
    ap.add_argument("--max-tokens", type=int, default=12000)
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--mode", default="longform", choices=["items", "longform"])
    ap.add_argument("--out", default=os.path.join(RAW, "local_tps.jsonl"))
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    client = LocalClient()
    mode = "w" if args.fresh else "a"
    t0 = time.perf_counter()
    print(f"L1 标定：{args.mode}，{args.repeats} 次 × ~{args.target_s:.0f}s，严格串行", flush=True)

    with open(args.out, mode, encoding="utf-8") as out_f:
        for rep in range(1, args.repeats + 1):
            topic = TOPICS[(rep - 1) % len(TOPICS)]
            msgs = [{"role": "user", "content": build_prompt(topic, args.words, args.mode)}]
            m = client.chat(
                msgs,
                max_completion_tokens=args.max_tokens,
                temperature=args.temperature,
                arm=f"localtps_{args.mode}",
                task_id=f"r{rep}",
                turn_index=rep,
                capture_chunks=True,
            )
            rec = {
                "phase": "LOCAL_TPS30", "mode": args.mode, "rep": rep, "topic": topic,
                "words": args.words, "target_s": args.target_s,
                "metrics": m.to_dict(), "ts": time.time(),
            }
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()

            hit = "OK " if abs(m.duration_s - args.target_s) <= 8 else "OFF"
            print(f"  [{hit}] rep{rep} dur={m.duration_s:6.2f}s gen={m.gen_s:6.2f}s "
                  f"ttft={m.ttft_s if m.ttft_s is not None else -1:5.2f}s "
                  f"out_tok={m.out_tokens:5d} think={m.think_tokens:4d} content={m.content_tokens:5d} "
                  f"tps={m.tps:6.1f} tps_content={m.tps_out:6.1f} "
                  f"gap_med={m.gap_median} burst={m.burst_frac} fin={m.finish_reason}",
                  flush=True)
            if m.error:
                print(f"       ERROR: {m.error[:200]}", flush=True)

    dt = time.perf_counter() - t0
    print(f"\ndone: {args.repeats} 次，串行耗时 {dt/60:.1f} min → {args.out}")


if __name__ == "__main__":
    main()
