# -*- coding: utf-8 -*-
"""现场演示脚本（视频录屏用）。

三个步骤，全部打到 stdout，方便直接录屏：
  1. 测出本机真实生成速率（预热 + 连续采样，展示它有多稳）
  2. 同一道题，问它「这条回复要写多久」——不注入 vs 注入稳定速率
  3. 长思考过程中，让它每写完一节就自报「已用时」，并把标记和真实流逝对齐

用法：
    python local/demo.py                # 完整演示
    python local/demo.py --steps 1,2    # 只跑某几步
    python local/demo.py --out demo.txt # 同时存一份文本
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from local.lclient import LocalClient  # noqa: E402
from local.exp_time_sense import (PROMPT_PRE, PROMPT_PROCESS, PROCESS_NSECT,  # noqa: E402
                                  parse_est, parse_markers, MARK_RE)

sys.stdout.reconfigure(encoding="utf-8")

RATE = 154.9          # 稳态实测速率（由 local/analyze_tps.py 给出）
TOPIC = "候鸟的迁徙"
N_ITEMS = 200


def line(c="─", n=62):
    print(c * n, flush=True)


def head(t):
    print("\n", flush=True)
    line("━")
    print(f"  {t}", flush=True)
    line("━")


def step1(client):
    head("步骤 1 · 这台机器的真实速度有多稳？")
    print("  （第一次请求要付 GPU 预热成本，不计入；之后连续采样）")
    warm = client.chat([{"role": "user", "content": "用一句话说明光合作用。"}],
                        max_completion_tokens=400, temperature=0.3)
    print(f"  预热请求（不计入）............ {warm.tps:6.1f} token/秒")
    rates = []
    for i in range(3):
        m = client.chat(
            [{"role": "user", "content":
              f"请写一篇至少 2000 字的中文长文，主题是「城市与海洋」，要具体，不要重复。"}],
            max_completion_tokens=8000, temperature=0.3)
        rates.append(m.tps)
        print(f"  采样 {i+1} ....................... {m.tps:6.1f} token/秒"
              f"   （实际生成 {m.gen_s:.1f} 秒 / {m.out_tokens} token）")
    ratio = max(rates) / min(rates)
    print(f"\n  → 稳定速率 ≈ {sum(rates)/len(rates):.1f} token/秒"
          f"（3 次采样波动只有 {ratio:.2f}×）")
    print(f"  → 对比：云端 API 同一测量是 2.39× 波动（后端路由到不同吞吐的轨道）")
    return sum(rates) / len(rates)


def step2(client, rate):
    head("步骤 2 · 告诉它速度，它估得准了吗？")
    print("  同一道题（写 200 条条目），第一行要求它独立预估生成耗时：")
    rows = []
    for label, sys_msg in (("不告诉它速度", "你是一个严谨、简洁的中文助手。"),
                            (f"告诉它 {rate:.1f} token/秒",
                             "你是一个严谨、简洁的中文助手。\n\n"
                             "## 运行反馈（外部计时器实测，单位可信）\n"
                             f"- 你的生成速度约为 {rate:.1f} token/秒（含思考过程在内的全部输出）。")):
        m = client.chat(
            [{"role": "system", "content": sys_msg},
             {"role": "user", "content": PROMPT_PRE.format(n=N_ITEMS, topic=TOPIC)}],
            max_completion_tokens=9000, temperature=0.3)
        est = parse_est(m.content)
        rows.append((label, est, m.gen_s))
        e = f"{est:.0f} 秒" if est else "未给出"
        ratio = f"（估/实际 {est/m.gen_s:.2f}×）" if est else ""
        print(f"  {label:22s}→ 它估计 {e:>7s}   实际 {m.gen_s:5.1f} 秒 {ratio}")
    if len(rows) == 2 and rows[0][1] and rows[1][1]:
        e0, a0 = rows[0][1], rows[0][2]
        e1, a1 = rows[1][1], rows[1][2]
        print(f"\n  → 不注入：误差 {abs(math.log(e0/a0)):.2f}（自然对数，约 {math.exp(abs(math.log(e0/a0))):.1f} 倍）")
        print(f"  → 注入后：误差 {abs(math.log(e1/a1)):.2f}（约 {math.exp(abs(math.log(e1/a1))):.1f} 倍）")
    return rows


def step3(client, rate):
    head("步骤 3 · 长思考过程中，它能边写边报时间吗？")
    per_sect_tok = 122.0
    per_sect_s = per_sect_tok / rate
    print(f"  要求：写成 12 个小节，每写完一节在末尾标一行〔已用时 X 秒〕")
    print(f"  注入：速率 {rate:.1f} token/秒 + 「每小节约产出 {per_sect_tok:.0f} 个 token"
          f" → 每小节约 {per_sect_s:.2f} 秒」")
    msgs = [
        {"role": "system", "content":
          "你是一个严谨、简洁的中文助手。\n\n"
          "## 运行反馈（外部计时器实测，单位可信）\n"
          f"- 你的生成速度约为 {rate:.1f} token/秒（含思考过程在内的全部输出）。\n"
          f"- 根据以往记录，你每写完一个小节大约产出 {per_sect_tok:.0f} 个 token，"
          f"因此每写完一个小节约耗时 {per_sect_s:.2f} 秒。"},
        {"role": "user", "content": PROMPT_PROCESS.format(words=1800, nsect=PROCESS_NSECT,
                                                          topic="候鸟的迁徙")},
    ]
    m = client.chat(msgs, max_completion_tokens=14000, temperature=0.3, capture_chunks=True)
    marks = parse_markers(m.content)
    times = m.chunk_times or []
    cc = m.chunk_content_chars or []
    think_s = max((m.think_end_s or 0) - (m.ttft_s or 0), 0)
    print(f"  （真实生成 {m.gen_s:.1f} 秒，其中思考阶段 {think_s:.1f} 秒）")
    print(f"\n  {'模型自报':>10s}   {'真实流逝':>10s}   {'差':>8s}")
    rows = []
    if marks and times and cc:
        for mo in MARK_RE.finditer(m.content):
            p = mo.start()
            cum, hit = 0, None
            for j, n in enumerate(cc):
                cum += n
                if cum > p:
                    hit = j
                    break
            if hit is None:
                hit = len(cc) - 1
            true_el = times[min(hit, len(times) - 1)] - (m.ttft_s or 0)
            val = float(mo.group(1))
            rows.append((val, true_el))
            print(f"  {val:8.1f} 秒   {true_el:8.1f} 秒   {val-true_el:+7.1f} 秒")
    if rows:
        last_m, last_t = rows[-1]
        print(f"\n  → 末标记 {last_m:.0f} 秒 / 真实 {last_t:.1f} 秒 = {last_m/last_t:.2f}×")
        print("  → 对照：只给速率不做单元换算时，这个倍数是 16×（模型在编等差数列）")
    else:
        print("\n  → 模型没有给出标记")
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default="1,2,3")
    ap.add_argument("--rate", type=float, default=RATE)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    steps = [s.strip() for s in args.steps.split(",") if s.strip()]

    print("=" * 64, flush=True)
    print("  本地模型时间感 · 现场演示", flush=True)
    print(f"  模型：{os.environ.get('LMSTUDIO_MODEL', 'google/gemma-4-e2b')}  @  "
          f"{os.environ.get('LMSTUDIO_BASE', 'http://127.0.0.1:1234/v1')}", flush=True)
    print("=" * 64, flush=True)

    client = LocalClient()
    rate = args.rate
    if "1" in steps:
        rate = step1(client)
    if "2" in steps:
        step2(client, rate)
    if "3" in steps:
        step3(client, rate)
    print("\n演示结束。", flush=True)


if __name__ == "__main__":
    main()
