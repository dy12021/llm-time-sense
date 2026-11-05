# -*- coding: utf-8 -*-
"""Phase B2 — 30 秒自持实验 + 剂量-反应设计。**每次实验清空上下文**，全程串行。

为什么要有 B2（Phase B v1 的两个缺陷）
--------------------------------------
1. **echo 缺陷**：v1 的 A 题把「目标 = 30 秒」写进了提示词，于是模型在
   「预计耗时：X」上 100% 复述 30。分不清「有独立预估能力」和「会抄题」。
   B2 **不告诉目标秒数**，只给确定性长度（条目数 N），模型必须对自己这条
   回复的生成时长做独立估计；地面真值 = 外部实测生成时长。
2. **剂量缺陷**：v1 的三个注入臂里，速率臂只注入了一个标定值，与基线的差异
   可能只是噪声。B2 改成**剂量-反应**：同一任务、同一措辞、只改注入的速率
   数字（40 / 76.5 / 120 token/秒）。
   - 预估随注入速率单调移动  => 这个数真的进了判断（速率被用起来了）
   - 预估不动              => 这个数没进判断（速率不产生时间感）
   76.5 是本机实测标定值；40 与 120 是**反事实剂量**，用于测敏感度，
   在报告中明确标注为反事实，不能当成「部署速率」。

三类臂
------
base        无任何反馈
speed_40    注入「约 40 token/秒」（反事实剂量）
speed_76    注入「约 76.5 token/秒」（实测标定中位）
speed_120   注入「约 120 token/秒」（反事实剂量）
elapsed     注入**真实的**同类生成实测耗时（取本臂上一条同类试验的实测值）

两类题
------
A2 自持 30 秒：输出恰好 N 条编号条目（确定性长度），第一行独立预估自己的
                生成耗时。真值 = 实测 gen_s。错误率 = med|ln(est/actual)|。
B2 纯换算：给 token 数，问需要多少秒。**不注入速率到题目里**，速率只在系统
            提示里按臂注入。关键读数是**隐含速率** = tokens / 模型答的秒数：
            base 给出模型默认假设自己有多快，注入臂给出它实际用了多少。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.client import LLMClient, load_llm_config  # noqa: E402
from harness import tasks as T  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

# Phase A items 模式标定：133 条 -> 正文 1750–2021 token，生成时长中位 30.9s
N_ITEMS = 133

TOPICS = [
    "城市与海洋", "候鸟的迁徙", "森林的水循环", "深海的热泉",
    "季风与农业", "候车的陌生人", "古树的年轮", "潮汐与港口",
]

# 剂量档位：76.5 是实测标定中位；40/120 是反事实剂量
DOSE_ARMS = {"speed_40": 40.0, "speed_76": None, "speed_120": 120.0}

PROMPT_A2 = """请输出恰好 {n} 条编号条目，每条一行，每条是一句关于「{topic}」的陈述。
只输出条目本身，不要标题、不要说明、不要空行。

回答的第一行先单独写一行，格式严格如下：
预计耗时：X
（X 取整数，是你独立估计这条回复从开始生成到结束需要多少秒）
从第二行开始写条目。"""

PROMPT_B2 = """现在有一段中文内容，共 {tokens} 个 token。
请只回答一个数字：生成这段内容大约需要多少秒？
只输出数字，不要解释，不要单位。"""

_EST_RE = re.compile(r"预计耗时\s*[::]?\s*[^0-9]{0,6}(\d+(?:\.\d+)?)")


def parse_est(text: str) -> float | None:
    """取「预计耗时：X」后面的数字；容忍「约 25 秒」「25秒」这类写法。"""
    if not text:
        return None
    m = _EST_RE.search(text.replace("：", ":"))
    if m:
        return float(m.group(1))
    return T.parse_seconds(text)


def load_calibration() -> dict:
    """合并 Phase A 两个数据集的实测正文速率，给出中位与 p10/p90。

    同时合并实测生成时长，给 elapsed 臂一个**真实**的首轮锚点（不用编造值）。
    """
    p = os.path.join(OUT, "tps_analysis.json")
    if not os.path.exists(p):
        raise SystemExit(f"缺少标定结果：{p}（先跑 analyze_tps.py）")
    d = json.load(open(p, encoding="utf-8"))
    vals, durs, srcs = [], [], []
    for name, v in d.items():
        if not v.get("tps_text"):
            continue
        vals.extend(v["tps_text"])
        durs.extend(v.get("duration") or [])
        srcs.append(name)
    if not vals:
        raise SystemExit(f"标定结果里没有可用的速率：{p}")
    vals = sorted(vals)
    n = len(vals)
    durs = sorted(durs)
    return {
        "source": "+".join(srcs),
        "median": vals[n // 2],
        "p10": vals[int(0.10 * n)],
        "p90": vals[min(int(0.90 * n), n - 1)],
        "min": vals[0], "max": vals[-1], "n_runs": n,
        "ratio": vals[-1] / max(vals[0], 1e-9),
        "median_duration": durs[len(durs) // 2] if durs else None,
    }


def eff_rate(arm: str, cal: dict) -> float | None:
    """本臂实际注入的速率（speed_76 = 实测标定中位，其余为反事实剂量）。"""
    if arm in DOSE_ARMS:
        r = DOSE_ARMS[arm]
        return cal["median"] if r is None else r
    return None


def build_system(arm: str, cal: dict, elapsed_hint: float | None) -> str:
    """只有反馈块不同——剂量臂之间的措辞完全一致，只有数字不同。"""
    if arm == "base":
        return T.SYSTEM_BASE
    if arm in DOSE_ARMS:
        rate = eff_rate(arm, cal)
        return (T.SYSTEM_BASE + "\n\n## 运行反馈（外部计时器实测）\n"
                f"- 实测生成速度：约 {rate:.0f} token/秒。")
    if arm == "elapsed":
        if elapsed_hint is None:
            return T.SYSTEM_BASE
        return (T.SYSTEM_BASE + "\n\n## 运行反馈（外部计时器实测）\n"
                f"- 上一次同类生成的实测耗时 {elapsed_hint:.1f} 秒。")
    raise ValueError(arm)


def rotate(seq, k):
    """把序列左旋 k 位——用来交错各臂的运行顺序。

    为什么必须交错：Phase B v1 固定按 base→speed_cal→speed_range→elapsed 顺序跑，
    如果部署在长程上漂移（速率本就会漂），臂效应和顺序效应就混在一起分不开。
    交错后每个臂在每个位置上出现的机会均等，顺序效应被均摊。
    """
    if not seq:
        return list(seq)
    k %= len(seq)
    return list(seq[k:]) + list(seq[:k])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="base,speed_40,speed_76,speed_120,elapsed")
    ap.add_argument("--a-trials", type=int, default=8, help="A2 题每臂重复次数")
    ap.add_argument("--b-reps", type=int, default=3, help="B2 题每个 token 档重复次数")
    ap.add_argument("--max-tokens", type=int, default=6000)
    ap.add_argument("--b-max-tokens", type=int, default=400)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--out", default=os.path.join(RAW, "phase_b2.jsonl"))
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--max-retries", type=int, default=6)
    args = ap.parse_args()

    cal = load_calibration()
    print(f"标定（{cal['source']}）：正文速率中位 {cal['median']:.1f} token/s，"
          f"p10–p90 {cal['p10']:.1f}–{cal['p90']:.1f}，n={cal['n_runs']}，"
          f"max/min={cal['ratio']:.2f}x", flush=True)
    print(f"剂量档位：speed_40=40（反事实） speed_76={cal['median']:.1f}（实测标定） "
          f"speed_120=120（反事实）", flush=True)

    # ---- resume: skip already-done (phase, arm, trial) -------------------
    done_keys = set()
    mode = "a"
    if args.fresh:
        mode = "w"
    elif os.path.exists(args.out):
        for line in open(args.out, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            done_keys.add((r["phase"], r["arm"], r["trial"]))
        mode = "a"
        print(f"续跑：已完成 {len(done_keys)} 条，跳过已做项", flush=True)

    client = LLMClient(load_llm_config())
    out_f = open(args.out, mode, encoding="utf-8")
    prev_t_last = None
    n_new = 0
    t0 = time.perf_counter()
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    # 每个臂最后一次同类试验的实测生成时长（elapsed 臂的真实锚点）
    elapsed_state = {a: cal.get("median_duration") for a in arms}

    def run(arm, phase, trial, msgs, max_tokens, extra):
        """一次调用 + 429 重试。严格串行：等待上一次调用完全结束。"""
        nonlocal prev_t_last, n_new
        for attempt in range(1, args.max_retries + 1):
            if prev_t_last is not None:
                assert time.perf_counter() >= prev_t_last - 1e-6, "请求区间重叠！并发了"
            m = client.chat(msgs, max_completion_tokens=max_tokens,
                            temperature=args.temperature, reasoning_effort=args.effort,
                            arm=arm, task_id=f"{phase}{trial}", turn_index=trial)
            prev_t_last = m.t_last
            if m.error and ("429" in m.error or "2056" in m.error):
                wait = 90 if "429" in m.error else 180
                print(f"       额度受限（{m.error[:80]}），{wait}s 后重试 "
                      f"({attempt}/{args.max_retries})", flush=True)
                time.sleep(wait)
                continue
            return m, extra
        return m, extra

    try:
        # ================= A2: 自持 30 秒（全新会话，臂交错执行） =========
        for k in range(1, args.a_trials + 1):
            topic = TOPICS[(k - 1) % len(TOPICS)]
            for arm in rotate(arms, k - 1):
                if ("B2_A2", arm, k) in done_keys:
                    continue
                elapsed_hint = elapsed_state[arm]
                sysmsg = build_system(arm, cal, elapsed_hint)
                prompt = PROMPT_A2.format(n=N_ITEMS, topic=topic)
                msgs = [{"role": "system", "content": sysmsg},
                        {"role": "user", "content": prompt}]
                m, _ = run(arm, "B2_A2", k, msgs, args.max_tokens, {})
                est = parse_est(m.content)
                rec = {"phase": "B2_A2", "arm": arm, "trial": k, "topic": topic,
                       "n_items": N_ITEMS,
                       "injected_rate": eff_rate(arm, cal),
                       "injected_elapsed_s": elapsed_hint,
                       "parsed": {"estimate_s": est,
                                  "echoes_item_count": (est == N_ITEMS)},
                       "metrics": m.to_dict(), "ts": time.time()}
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_f.flush()
                n_new += 1
                # elapsed 臂的下一个真实锚点 = 本条实测生成时长
                elapsed_state[arm] = m.gen_s
                print(f"  [A2 {arm:<10}] k{k} est={est} gen={m.gen_s:6.2f}s "
                      f"tok={m.out_tokens:5d} think={m.think_tokens:4d} "
                      f"tps={m.tps:6.1f} finish={m.finish_reason}"
                      + (f"  ERR={m.error[:60]}" if m.error else ""), flush=True)

        # ================= B2: 纯换算（速率只在系统提示里，臂交错执行） ===
        for rep in range(1, args.b_reps + 1):
            for tokens in (500, 1500, 3000, 4500):
                for arm in rotate(arms, rep - 1):
                    key = ("B2_B2", arm, f"{tokens}_{rep}")
                    if key in done_keys:
                        continue
                    elapsed_hint = elapsed_state[arm]
                    sysmsg = build_system(arm, cal, elapsed_hint)
                    prompt = PROMPT_B2.format(tokens=tokens)
                    msgs = [{"role": "system", "content": sysmsg},
                            {"role": "user", "content": prompt}]
                    m, _ = run(arm, "B2_B2", f"{tokens}_{rep}", msgs,
                               args.b_max_tokens, {})
                    est = T.parse_seconds(m.content)
                    rec = {"phase": "B2_B2", "arm": arm, "trial": f"{tokens}_{rep}",
                           "tokens": tokens,
                           "injected_rate": eff_rate(arm, cal),
                           "injected_elapsed_s": elapsed_hint,
                           "parsed": {"estimate_s": est},
                           "metrics": m.to_dict(), "ts": time.time()}
                    out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out_f.flush()
                    n_new += 1
                    implied = (tokens / est) if est else None
                    if implied:
                        print(f"  [B2 {arm:<10}] {tokens:>5} tok -> 答 {est} "
                              f"(隐含速率 {implied:.1f} tok/s)", flush=True)
                    else:
                        print(f"  [B2 {arm:<10}] {tokens:>5} tok -> 答 {est}", flush=True)
                    elapsed_state[arm] = m.gen_s
    finally:
        out_f.close()

    dt = time.perf_counter() - t0
    print(f"\ndone: 新增 {n_new} 条，总耗时 {dt/60:.1f} min（严格串行，每次清空上下文）")


if __name__ == "__main__":
    main()
