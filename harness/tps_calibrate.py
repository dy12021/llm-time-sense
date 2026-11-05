# -*- coding: utf-8 -*-
"""Phase A — stable TPS calibration. STRICTLY SEQUENTIAL, no concurrency.

Why this file exists
--------------------
The previous 450-turn experiment found TPS swinging ~3.5x (p90/p10) across
turns. That number carried the whole "physical side" argument, so it deserves
a clean, dedicated measurement with:
  * exactly one request in flight at any moment,
  * controlled output length,
  * controlled context length,
  * per-chunk arrival times (to tell a real length effect apart from the
    server batching the stream and inflating gen_s).

NO-CONCURRENCY GUARANTEE
-------------------------
Every call records [t_request, t_last]. analyze_tps.py asserts that no two
intervals overlap. If they ever do, the run is reported as contaminated.
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

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")

# ---------------------------------------------------------------- A1: output length
# The prompt pins the number of items so the output length is set by the
# instruction, not by chance. Each item is ~15-20 Chinese tokens.
A1_LENGTHS = [
    ("L01_items3", 3),
    ("L02_items8", 8),
    ("L03_items20", 20),
    ("L04_items50", 50),
    ("L05_items120", 120),
]

A1_PROMPT = ("请输出恰好 {n} 条编号条目，每条一行，每条是一句关于「海洋与陆地生态差异」的陈述。"
             "只输出条目本身，不要任何其他内容。")


# ---------------------------------------------------------------- A2: context length
FILLER = ("以下是一段用于填充上下文的参考资料，内容关于候鸟迁徙与湿地保护的历史与研究。"
          "它本身与后面的任务无关，只是用来改变送入模型的上下文长度。")


def build_context(n_tokens: int) -> list[dict]:
    if n_tokens <= 0:
        return []
    # roughly 1 CJK char ~ 1 token; repeat + number to keep it varied
    body = FILLER * max(1, n_tokens // 20)
    return [{"role": "user", "content": body}]


def run_a1(client, records, out_f, repeats, effort, temperature, max_tokens, warmup):
    print("=== A1 输出长度效应 ===", flush=True)
    for label, n_items in A1_LENGTHS:
        prompt = A1_PROMPT.format(n=n_items)
        for rep in range(1, repeats + 1):
            m = client.chat(
                [{"role": "user", "content": prompt}],
                max_completion_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=effort,
                arm="calib_outlen",
                task_id=label,
                turn_index=rep,
                capture_chunks=True,
            )
            rec = {
                "phase": "A1", "label": label, "n_items": n_items, "rep": rep,
                "warmup": rep <= warmup, "metrics": m.to_dict(), "ts": time.time(),
            }
            records.append(rec)
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            print(f"  {label:<14} rep{rep} dur={m.duration_s:6.2f}s gen={m.gen_s:6.2f}s "
                  f"ttft={m.ttft_s if m.ttft_s is not None else -1:5.2f}s "
                  f"out_tok={m.out_tokens:5d} think={m.think_tokens:4d} "
                  f"tps={m.tps:6.1f} gap_med={m.gap_median} gap_p95={m.gap_p95} "
                  f"burst={m.burst_frac}", flush=True)


def run_a2(client, records, out_f, repeats, effort, temperature, max_tokens, warmup,
           ctx_tokens):
    print("=== A2 上下文长度效应 ===", flush=True)
    prompt = "请用两句话说明什么是候鸟的迁徙路线。"
    for n_tok in ctx_tokens:
        for rep in range(1, repeats + 1):
            msgs = build_context(n_tok) + [{"role": "user", "content": prompt}]
            m = client.chat(
                msgs,
                max_completion_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=effort,
                arm="calib_ctxlen",
                task_id=f"ctx{n_tok}",
                turn_index=rep,
                capture_chunks=True,
            )
            rec = {
                "phase": "A2", "label": f"ctx{n_tok}", "ctx_tokens": n_tok, "rep": rep,
                "warmup": rep <= warmup, "metrics": m.to_dict(), "ts": time.time(),
            }
            records.append(rec)
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            print(f"  ctx={n_tok:<7} rep{rep} dur={m.duration_s:6.2f}s ttft={m.ttft_s if m.ttft_s is not None else -1:6.2f}s "
                  f"gen={m.gen_s:5.2f}s out_tok={m.out_tokens:4d} tps={m.tps:6.1f} "
                  f"prompt_tok={m.prompt_tokens}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=8)
    ap.add_argument("--ctx-repeats", type=int, default=3)
    ap.add_argument("--ctx-tokens", default="0,2000,8000,20000,40000")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--max-tokens", type=int, default=4000)
    ap.add_argument("--warmup", type=int, default=1, help="前 N 次标记为 warmup，不计入主统计")
    ap.add_argument("--out", default=os.path.join(RAW, "tps_calibration.jsonl"))
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--phase", default="A1,A2")
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    client = LLMClient(load_llm_config())
    records = []
    mode = "w" if args.fresh else "a"
    t0 = time.perf_counter()
    with open(args.out, mode, encoding="utf-8") as out_f:
        for ph in args.phase.split(","):
            if ph == "A1":
                run_a1(client, records, out_f, args.repeats, args.effort,
                       args.temperature, args.max_tokens, args.warmup)
            elif ph == "A2":
                run_a2(client, records, out_f, args.ctx_repeats, args.effort,
                       args.temperature, args.max_tokens, args.warmup,
                       [int(x) for x in args.ctx_tokens.split(",")])
    dt = time.perf_counter() - t0
    tot = sum(r["metrics"]["out_tokens"] for r in records)
    print(f"\ndone: {len(records)} calls in {dt/60:.1f} min, output tokens={tot}")


if __name__ == "__main__":
    main()
