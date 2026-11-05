# -*- coding: utf-8 -*-
"""本地模型（google/gemma-4-e2b）上的时间感实验。

三个子实验，都严格串行、单请求：

pre       事前预估 + 剂量-反应（对照上一轮 Phase B2 的 A2 自持题）
          题面**不出现**目标秒数；只改注入的速率数字。
          读数：预估值是否随注入速率单调移动（剂量-反应斜率 b）。

posthoc   事后预估（**故意保留上下文**：模型需要看着自己刚写完的东西，
          才能估出「大概写了多少 token」→ 除以速率 → 得到耗时）
          这是「速率→时间感」最干净的一个测法。
          读数：预估值与**真实耗时**的跨轮相关性，以及相对基线的误差下降。

process  过程时间感（长思考状态）：模型在一条长回复里边写边标
          「〔已用时 X 秒〕」，每个标记定位到流里的**真实经过秒数**再对表。
          读数：同一轮内「标记值 vs 真实流逝」的相关；末标记/真实倍数。
          ★ 这一项针对「长思考」：思维链 token 也占真实时间，但模型看不见它，
          正是误差的来源，也是要优化的地方。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from local.lclient import LocalClient  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

TOPICS = [
    "城市与海洋", "候鸟的迁徙", "森林的水循环", "深海的热泉",
    "季风与农业", "候车的陌生人", "古树的年轮", "潮汐与港口",
]

# --------------------------------------------------------------------------
# 反馈渲染（与 harness/tasks.py 同口径：只有反馈块不同）
# --------------------------------------------------------------------------
SYS_BASE = "你是一个严谨、简洁的中文助手。"
FEEDBACK_HEADER = "## 运行反馈（外部计时器实测，单位可信）"


def sys_for_arm(arm: str, rate: float | None, elapsed: float | None) -> str:
    if arm == "base":
        return SYS_BASE
    lines = []
    if arm.startswith("speed"):
        lines.append(f"- 你的生成速度约为 {rate:.1f} token/秒（含思考过程在内的全部输出）。")
        if arm == "speed_len":
            lines.append("- 粗略换算：中文大约 1 个汉字 ≈ 0.7 个 token。")
    elif arm == "elapsed":
        lines.append(f"- 你上一轮从开始到结束共耗时约 {elapsed:.1f} 秒。")
    else:
        raise ValueError(arm)
    return SYS_BASE + "\n\n" + FEEDBACK_HEADER + "\n" + "\n".join(lines)


# --------------------------------------------------------------------------
# pre：事前预估（题面不含目标秒数）
# --------------------------------------------------------------------------
PRE_N_ITEMS = 200

PROMPT_PRE = """请输出恰好 {n} 条编号条目，每条一行，每条是一句关于「{topic}」的陈述。
只输出条目本身，不要标题、不要说明、不要空行。

回答的第一行先单独写一行，格式严格如下：
预计耗时：X
（X 取整数，是你独立估计这条回复从开始生成到结束需要多少秒）
从第二行开始写条目。"""

_EST_RE = re.compile(r"预计耗时\s*[:：]?\s*[^0-9]{0,6}(\d+(?:\.\d+)?)")


def parse_est(text: str) -> float | None:
    if not text:
        return None
    m = _EST_RE.search(text.replace("：", ":"))
    if m:
        return float(m.group(1))
    m2 = re.search(r"(\d+(?:\.\d+)?)\s*秒", text)
    if m2:
        return float(m2.group(1))
    nums = re.findall(r"(\d+(?:\.\d+)?)", text)
    return float(nums[-1]) if nums else None


# --------------------------------------------------------------------------
# posthoc：事后预估（保留上一条回复在上下文里）
# --------------------------------------------------------------------------
POST_PROMPT_WRITE = """请写一篇 {words} 字左右的中文短文，主题是「{topic}」。
内容要具体，可以举例子。只输出正文，不要标题，不要列表，不要解释。"""

PROMPT_POST = """关于你上一条回复，请只回答一个问题：
你上一条回复（从开始生成到结束）大约用了多少秒？

严格按下面格式输出，只写这两行：
预计耗时：X
估计token数：Y
（X 取整数，是你估计的上一条回复从开始生成到结束所用的秒数；
 Y 取整数，是你估计的上一条回复大约有多少个 token）"""

_TOK_RE = re.compile(r"估计token数\s*[:：]?\s*[^0-9]{0,6}(\d+(?:\.\d+)?)")


def parse_tokens(text: str) -> float | None:
    if not text:
        return None
    m = _TOK_RE.search(text.replace("：", ":"))
    if m:
        return float(m.group(1))
    return None


# --------------------------------------------------------------------------
# process：过程时间感（长思考状态，编号小节 + 内联标记）
# --------------------------------------------------------------------------
PROCESS_NSECT = 12

# 本地模型会把标记写成「〔已用时 15〕」（不带「秒」字），所以「秒」可选
MARK_RE = re.compile(r"[（(〔【]\s*已用时\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:秒)?\s*[)）〕】]")

PROMPT_THINK_ONLY = """先不要写正文。请认真思考下面这个写作任务，把你想写的内容、每个小节的大致篇幅都想清楚。

任务：写一篇 {words} 字左右的中文长文，主题是「{topic}」，写成 {nsect} 个小节。

只输出你的写作计划，不要写正文。"""

PROMPT_PROCESS = """请写一篇 {words} 字左右的中文长文，主题是「{topic}」。
要求：写成 {nsect} 个小节，每个小节用「## 小节 N」开头，N 从 1 到 {nsect}。
内容要具体，可以举例子、给数据、描述细节。

**标记要求（务必遵守）**：每写完一个小节，就在该小节的**末尾**单独加一行
〔已用时 X 秒〕
X 取整数，是你估计的「从本次回复开始生成，到这个小节写完为止」一共过了多少秒。
全文共 {nsect} 个小节，**每一个**小节的末尾都要有一行标记，**不是只在小节 1 后面标**。"""


def parse_markers(text: str) -> list[float]:
    """取出所有 〔已用时 X 秒〕 标记里的 X。"""
    return [float(m.group(1)) for m in MARK_RE.finditer(text or "")]


def marker_offsets(text: str) -> list[int]:
    """每个标记在正文里的字符偏移（用于定位真实经过秒数）。"""
    return [m.start() for m in MARK_RE.finditer(text or "")]


# --------------------------------------------------------------------------
def load_rate(mode: str = "longform") -> float:
    """取该任务形态的**热态**实测速率中位（排除第 1 次冷启动请求）。

    注入的速率必须等于模型在这个任务形态下真实跑出来的速率，
    否则「注入速率→时间感」测的就是一个反事实数字。
    """
    p = os.path.join(OUT, "local_tps_summary.json")
    if not os.path.exists(p):
        raise SystemExit("缺少本地标定结果（先跑 local/calib.py + local/analyze_tps.py）")
    d = json.load(open(p, encoding="utf-8"))
    w = (d.get("per_mode_warm") or {}).get(mode)
    if w and w.get("median"):
        return float(w["median"])
    if d.get("warm", {}).get("median"):
        return float(d["warm"]["median"])
    raise SystemExit(f"标定结果里没有 {mode} 的热态速率")


def run_pre(args, client, rate_true: float, out_f):
    doses = {
        "base": None,
        "speed_low": rate_true * 0.5,
        "speed_true": rate_true,
        "speed_high": rate_true * 1.6,
        "elapsed": None,
    }
    arms = list(doses)
    recs = []
    last_actual = None          # 上一次同类实测耗时（elapsed 臂的真实锚点）
    for rep in range(1, args.repeats + 1):
        order = arms[rep % len(arms):] + arms[:rep % len(arms)]   # 逐轮交错
        for arm in order:
            topic = TOPICS[(rep - 1) % len(TOPICS)]
            rate = doses[arm]
            elapsed = None
            if arm == "elapsed":
                # 注入**真实**的同类实测耗时（不是编的值）：取最近一次同类试验的实测 gen_s
                elapsed = last_actual if last_actual else 25.0
            sys_msg = sys_for_arm(arm, rate or rate_true, elapsed)
            msgs = [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": PROMPT_PRE.format(n=PRE_N_ITEMS, topic=topic)},
            ]
            m = client.chat(msgs, max_completion_tokens=9000, temperature=0.3,
                            arm=arm, task_id=f"r{rep}", turn_index=rep)
            est = parse_est(m.content)
            rec = {
                "phase": "LOCAL_PRE", "rep": rep, "arm": arm, "topic": topic,
                "injected_rate": rate, "rate_true": rate_true,
                "est_s": est, "metrics": m.to_dict(), "ts": time.time(),
            }
            recs.append(rec)
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            last_actual = m.gen_s
            act = m.gen_s
            if est and est > 0 and act > 0:
                err = f"{abs(math.log(est / act)):.2f}"
            else:
                err = "NA"
            print(f"  pre r{rep} {arm:11s} est={est if est is None else round(est, 1)!s:>6} "
                  f"actual={act:6.2f}s tps={m.tps:6.1f} think={m.think_tokens:4d} err={err}",
                  flush=True)
    return recs


def run_posthoc(args, client, rate_true: float, out_f):
    """事后预估：故意保留上一条回复在上下文里。

    关键设计：**每轮要求的长度不同**（500→3000 字）。
    如果每轮长度一样，真实耗时就几乎是常数，「预估与真实耗时相关」这件事根本没法测；
    长度拉开之后，真实耗时变化 5–6 倍，才能看出模型是在跟着现实走还是在喊一个固定数字。
    """
    arms = ["base", "speed", "elapsed"]
    lengths = [500, 1000, 1500, 2000, 2500, 3000]
    recs = []
    last_actual = None          # 上一条实测耗时（elapsed 臂的真实锚点）
    for rep in range(1, args.repeats + 1):
        order = arms[rep % len(arms):] + arms[:rep % len(arms)]
        words = lengths[(rep - 1) % len(lengths)]
        for arm in order:
            topic = TOPICS[(rep - 1) % len(TOPICS)]
            rate = rate_true
            elapsed = None
            if arm == "elapsed":
                # 注入**真实**的同类实测耗时（不是编的值）：取最近一次实测 gen_s
                elapsed = last_actual if last_actual else 10.0
            if arm == "base":
                sys_msg = SYS_BASE
            else:
                lines = [f"- 你的生成速度约为 {rate:.1f} token/秒（含思考过程在内的全部输出）。"]
                if arm == "elapsed":
                    lines = [f"- 你上一轮从开始到结束共耗时约 {elapsed:.1f} 秒。"]
                sys_msg = SYS_BASE + "\n\n" + FEEDBACK_HEADER + "\n" + "\n".join(lines)
            msgs = [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": POST_PROMPT_WRITE.format(words=words, topic=topic)},
            ]
            m1 = client.chat(msgs, max_completion_tokens=9000, temperature=0.3,
                             arm=arm + "_write", task_id=f"r{rep}", turn_index=rep)
            # ★ 故意保留上一条回复在上下文里：模型要估「我写了多少 token」才谈得上时间感
            msgs2 = msgs + [
                {"role": "assistant", "content": m1.content},
                {"role": "user", "content": PROMPT_POST},
            ]
            m2 = client.chat(msgs2, max_completion_tokens=1200, temperature=0.2,
                             arm=arm + "_probe", task_id=f"r{rep}", turn_index=rep)
            est = parse_est(m2.content)
            est_tok = parse_tokens(m2.content)
            rec = {
                "phase": "LOCAL_POSTHOC", "rep": rep, "arm": arm, "topic": topic,
                "requested_words": words,
                "injected_rate": rate if arm == "speed" else None,
                "injected_elapsed_s": elapsed,
                "est_s": est, "est_tokens": est_tok,
                "write_metrics": m1.to_dict(), "probe_metrics": m2.to_dict(),
                "ts": time.time(),
            }
            recs.append(rec)
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            last_actual = m1.gen_s
            print(f"  post r{rep} {arm:8s} words={words:5d} est={est if est is None else round(est,1)!s:>6} "
                  f"actual_gen={m1.gen_s:6.2f}s write_tok={m1.out_tokens:5d} "
                  f"tps={m1.tps:6.1f}", flush=True)
    return recs


def run_process(args, client, rate_true: float, out_f):
    arms = ["base", "speed", "speed_len"]
    recs = []
    for rep in range(1, args.repeats + 1):
        order = arms[rep % len(arms):] + arms[:rep % len(arms)]
        for arm in order:
            topic = TOPICS[(rep - 1) % len(TOPICS)]
            sys_msg = sys_for_arm(arm, rate_true, None)
            msgs = [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": PROMPT_PROCESS.format(
                    words=args.words, nsect=PROCESS_NSECT, topic=topic)},
            ]
            m = client.chat(msgs, max_completion_tokens=14000, temperature=0.3,
                            arm=arm, task_id=f"r{rep}", turn_index=rep, capture_chunks=True)
            marks = parse_markers(m.content)
            offs = marker_offsets(m.content)
            rec = {
                "phase": "LOCAL_PROCESS", "rep": rep, "arm": arm, "topic": topic,
                "injected_rate": rate_true if arm != "base" else None,
                "n_marks": len(marks), "marks": marks, "mark_offsets": offs,
                "metrics": m.to_dict(), "ts": time.time(),
            }
            recs.append(rec)
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            print(f"  proc r{rep} {arm:10s} marks={len(marks):2d}/{PROCESS_NSECT} "
                  f"gen={m.gen_s:6.2f}s think={m.think_tokens:5d} cont={m.content_tokens:5d} "
                  f"last_mark={marks[-1] if marks else None}", flush=True)
    return recs


def run_process2(args, client, rate_true: float, out_f):
    """长思考优化：两段式（先思考 → 外部时钟在思考结束时注入 → 再写正文）。

    为什么这么设计：一次生成里，模型**看不见自己思考了多久**，
    所以「从开始生成算起已过多少秒」这件事在长思考下天然算不准。
    工程上唯一能修的就是：**在思考结束的节点把时钟喂回去**，
    这正是真实 agent 循环的做法。

    三个臂：
      base    不给速率、不给时钟
      speed   只给稳定速率（对照：纯速率够不够）
      clock   给稳定速率 + 「你上一轮思考已经用了 T 秒」（T = 实测思考耗时）
    """
    arms = ["base", "speed", "clock"]
    recs = []
    for rep in range(1, args.repeats + 1):
        order = arms[rep % len(arms):] + arms[:rep % len(arms)]
        for arm in order:
            topic = TOPICS[(rep - 1) % len(TOPICS)]
            # --- 第 1 段：只思考 ---
            sys1 = SYS_BASE
            if arm in ("speed", "clock"):
                sys1 = (SYS_BASE + "\n\n" + FEEDBACK_HEADER +
                        f"\n- 你的生成速度约为 {rate_true:.1f} token/秒（含思考过程在内的全部输出）。")
            t1 = client.chat(
                [{"role": "system", "content": sys1},
                 {"role": "user", "content": PROMPT_THINK_ONLY.format(
                     words=args.words, nsect=PROCESS_NSECT, topic=topic)}],
                max_completion_tokens=4000, temperature=0.3,
                arm=arm + "_think", task_id=f"r{rep}", turn_index=rep, capture_chunks=True)
            think_s = t1.gen_s
            # --- 第 2 段：带时钟写正文 ---
            sys2 = SYS_BASE
            if arm in ("speed", "clock"):
                sys2 = (SYS_BASE + "\n\n" + FEEDBACK_HEADER +
                        f"\n- 你的生成速度约为 {rate_true:.1f} token/秒（含思考过程在内的全部输出）。")
            if arm == "clock":
                sys2 += f"\n- 你上一轮的思考实际用了 {think_s:.1f} 秒。"
            msgs = [
                {"role": "system", "content": sys2},
                {"role": "user", "content": PROMPT_PROCESS.format(
                    words=args.words, nsect=PROCESS_NSECT, topic=topic)},
            ]
            m = client.chat(msgs, max_completion_tokens=14000, temperature=0.3,
                            arm=arm, task_id=f"r{rep}", turn_index=rep, capture_chunks=True)
            marks = parse_markers(m.content)
            rec = {
                "phase": "LOCAL_PROCESS2", "rep": rep, "arm": arm, "topic": topic,
                "injected_rate": rate_true if arm != "base" else None,
                "think_s": think_s, "injected_elapsed_s": think_s if arm == "clock" else None,
                "n_marks": len(marks), "marks": marks,
                "metrics": m.to_dict(), "think_metrics": t1.to_dict(), "ts": time.time(),
            }
            recs.append(rec)
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            print(f"  proc2 r{rep} {arm:6s} think={think_s:5.1f}s marks={len(marks):2d} "
                  f"write={m.gen_s:6.2f}s total={(think_s + m.gen_s):6.2f}s "
                  f"last_mark={marks[-1] if marks else None}", flush=True)
    return recs


def _typical_think_s() -> float:
    """从已跑的长规格数据里取「思考阶段耗时中位」。

    模型在正文开始前先想一遍，那段时间是真实流逝、但模型自己看不见，
    所以在注入单元换算时必须把它单独补上，否则整体会差一个常数。
    """
    p = os.path.join(RAW, "local_process.jsonl")
    vals = []
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            m = r.get("metrics") or {}
            t = m.get("think_end_s")
            ttft = m.get("ttft_s")
            if t is not None and ttft is not None:
                vals.append(max(t - ttft, 0.0))
    if not vals:
        return 3.0
    vals.sort()
    return vals[len(vals) // 2]


def run_process_opt(args, client, rate_true: float, out_f):
    """长思考优化臂：光给速率没用，得给「工作单元 ↔ 时间」的换算。

    L3 看到的失败模式：模型把标记写成一个**等差数列**（15、32、50…），
    但它显然是编的（真实每小节只花 1 秒多）。原因是它只会写，不会算——
    它不知道自己写了多少字、也不知道自己有多快。

    这里给两样东西：
      1. 稳定速率 R（token/秒）
      2. 「每写完一个小节大约产出 N 个 token」→ 换算成「每小节约 N/R 秒」
    模型只要会数自己写到第几个小节，就能推出大概过了多久。

    再加一个臂把「思考阶段的耗时」也补上（那是模型看不见的真实流逝）。
    """
    # 每小节产出 token 数：用已跑数据的中位（12 个小节的正文 token / 12）
    per_sect_tok = None
    p = os.path.join(RAW, "local_process.jsonl")
    if os.path.exists(p):
        vals = []
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            m = r.get("metrics") or {}
            ct = m.get("content_tokens")
            if ct:
                vals.append(ct / max(r.get("n_marks") or 12, 1))
        if vals:
            vals.sort()
            per_sect_tok = vals[len(vals) // 2]
    if not per_sect_tok:
        per_sect_tok = 120.0
    per_sect_s = per_sect_tok / rate_true
    think_s = _typical_think_s()
    print(f"  [优化臂参数] 速率 {rate_true:.1f} tok/s · 每小节约 {per_sect_tok:.0f} token "
          f"→ 每小节约 {per_sect_s:.2f} 秒 · 思考阶段典型耗时 {think_s:.1f} 秒", flush=True)

    arms = ["speed_unit", "speed_unit_think"]
    recs = []
    for rep in range(1, args.repeats + 1):
        order = arms[rep % len(arms):] + arms[:rep % len(arms)]
        for arm in order:
            topic = TOPICS[(rep - 1) % len(TOPICS)]
            lines = [f"- 你的生成速度约为 {rate_true:.1f} token/秒（含思考过程在内的全部输出）。",
                     f"- 根据以往记录，你每写完一个小节大约产出 {per_sect_tok:.0f} 个 token，"
                     f"因此每写完一个小节约耗时 {per_sect_s:.2f} 秒。"]
            if arm == "speed_unit_think":
                lines.append(f"- 你在开始写正文之前的思考阶段大约用了 {think_s:.1f} 秒，"
                             f"这段时间也算进总耗时。")
            sys_msg = SYS_BASE + "\n\n" + FEEDBACK_HEADER + "\n" + "\n".join(lines)
            msgs = [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": PROMPT_PROCESS.format(
                    words=args.words, nsect=PROCESS_NSECT, topic=topic)},
            ]
            m = client.chat(msgs, max_completion_tokens=14000, temperature=0.3,
                            arm=arm, task_id=f"r{rep}", turn_index=rep, capture_chunks=True)
            marks = parse_markers(m.content)
            rec = {
                "phase": "LOCAL_PROCESS_OPT", "rep": rep, "arm": arm, "topic": topic,
                "injected_rate": rate_true,
                "per_sect_tok": per_sect_tok, "per_sect_s": per_sect_s,
                "injected_think_s": think_s if arm == "speed_unit_think" else None,
                "n_marks": len(marks), "marks": marks,
                "metrics": m.to_dict(), "ts": time.time(),
            }
            recs.append(rec)
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            print(f"  procopt r{rep} {arm:16s} marks={len(marks):2d} gen={m.gen_s:6.2f}s "
                  f"think={m.think_tokens:4d} marks={marks[:6]}", flush=True)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sub", choices=["pre", "posthoc", "process", "process2", "process_opt"])
    ap.add_argument("--repeats", type=int, default=6)
    ap.add_argument("--words", type=int, default=1800)
    ap.add_argument("--rate", type=float, default=None, help="注入的实测速率；默认读标定结果")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rate_true = args.rate if args.rate else load_rate(
        "items" if args.sub == "pre" else "longform")
    client = LocalClient()
    os.makedirs(RAW, exist_ok=True)
    out_path = args.out or os.path.join(RAW, f"local_{args.sub}.jsonl")
    mode = "w" if not os.path.exists(out_path) else "a"
    print(f"=== local {args.sub} · rate_true={rate_true:.1f} tok/s · {args.repeats} 轮 × 3~5 臂 ===",
          flush=True)
    t0 = time.perf_counter()
    with open(out_path, mode, encoding="utf-8") as out_f:
        if args.sub == "pre":
            run_pre(args, client, rate_true, out_f)
        elif args.sub == "posthoc":
            run_posthoc(args, client, rate_true, out_f)
        elif args.sub == "process2":
            run_process2(args, client, rate_true, out_f)
        elif args.sub == "process_opt":
            run_process_opt(args, client, rate_true, out_f)
        else:
            run_process(args, client, rate_true, out_f)
    print(f"done in {(time.perf_counter()-t0)/60:.1f} min → {out_path}", flush=True)


if __name__ == "__main__":
    main()
