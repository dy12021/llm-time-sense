# -*- coding: utf-8 -*-
"""Experimental arms, task suites and prompt templates.

ARMS (the only thing that differs between arms is the feedback block):
  base        no feedback at all
  speed       only the previous cycle's throughput:  "约 X token/秒"
  speed_count previous cycle's token count + throughput
  elapsed     only the previous cycle's wall-clock duration: "约 X 秒"

Why these four:
  base vs speed          -> the user's core hypothesis (does TPS create time sense?)
  speed vs speed_count   -> is a speed number enough without knowing how much you wrote?
  speed vs elapsed       -> is throughput the active ingredient, or is any timing number?
  elapsed                -> positive control: a directly usable number should be used well.
"""
from __future__ import annotations

import json
import re

ARMS = ["base", "speed", "speed_count", "elapsed", "speed_cum"]

SYSTEM_BASE = "你是一个严谨、简洁的中文助手。"

FEEDBACK_HEADER = "## 运行反馈（外部计时器实测，单位可信）"

# --------------------------------------------------------------------------
# S1 — length calibration: does the model know how long its own reply takes?
#   turn A: commit to an estimate of its own reply duration, then answer  (pre-estimate)
#   turn B: report how long the previous reply actually took                (post-hoc)
# --------------------------------------------------------------------------

S1_TASKS = [
    ("t1_1liner", "用一句话说明光合作用。", 40),
    ("t2_3sent", "用三句话解释什么是通货膨胀。", 90),
    ("t3_list10", "列出 10 条「深夜喝水会影响睡眠」的理由，每条一行。", 220),
    ("t4_para", "写一段 200 字左右的中文短文，主题是「城市里的雨」。", 300),
    ("t5_code", "写一个 Python 函数 is_palindrome(s) 判断字符串是否为回文，并附 3 条示例用法。", 220),
    ("t6_essay", "写一篇 600 字左右的中文短文，解释为什么天空是蓝色的。", 850),
]

S1_PROMPT_ESTIMATE = """用户任务：{task}

请按下面的格式回答，第一行先给出估计，再写正文：
预计耗时：X
（X 是你估计这条回复从开始生成到结束大约需要的秒数，取整数；只写数字）
然后另起一行写出这条回复的正文。"""

S1_PROMPT_REPORT = """请只回答一个问题：你上一条回复（从开始生成到结束）大约用了多少秒？
严格按下面格式输出，只写这一行：
回复耗时秒数：X
（X 取整数，X 是你估计的秒数）"""

# --------------------------------------------------------------------------
# S2 — fixed duration: can it size its reply to hit a wall-clock target?
#   turn A: write something that should take ~N seconds
#   turn B: self-report its own token count + the strategy it used
# --------------------------------------------------------------------------

S2_TARGETS = [3, 8, 20]

S2_PROMPT_WRITE = """请写一段内容，使它自己的生成耗时（从开始生成到结束）大约为 {n} 秒。
内容主题：{topic}
直接开始写正文，不要写任何解释或计划。"""

S2_PROMPT_PROBE = """请回答两个问题，输出为一个 JSON 对象，不要有多余文字：
{{"tokens": <你上一条回复大约多少个 token，取整数>, "strategy": "<你在写之前是否规划了长度？如果规划了，你是怎么估算这个长度的？用一句话说明>"}}"""

S2_TOPICS = {
    3: "雨后的城市街道",
    8: "为什么深海生物会发光",
    20: "一次完整的日落是如何发生的",
}

# --------------------------------------------------------------------------
# S3 — long horizon: can it keep a running sense of elapsed time?
#   12 turns in one session; odd turns ask for elapsed-since-session-start,
#   even turns ask for the previous reply's duration.
# --------------------------------------------------------------------------

S3_TASKS = [
    "用一句话说明什么是 API。",
    "列出 3 个 Python 常用库并各用一句话说明用途。",
    "把这句话改写得更正式：「别在这儿抽烟。」",
    "解释一下什么是哈希表。",
    "给出一个去除字符串首尾空格的方法（任意语言）。",
    "写一句关于秋天的诗句。",
    "用两点说明为什么数据库要建索引。",
    "给初学者解释什么是递归。",
    "把「会议改到下午三点」改写成一句邮件措辞。",
    "简述 HTTP 与 HTTPS 的区别。",
    "给出一个二分查找的伪代码。",
    "用一句话描述什么是单元测试。",
]

S3_PROMPT_ELAPSED = """{task}

最后请补一行，严格用下面格式输出这一行（不要加别的内容）：
已过秒数：X
（X 取整数，是你估计的从本次会话开始到现在的秒数）"""

S3_PROMPT_PREV = """{task}

最后请补一行，严格用下面格式输出这一行（不要加别的内容）：
回复耗时秒数：X
（X 取整数，是你估计的上一条回复从开始生成到结束的秒数）"""

# --------------------------------------------------------------------------
# feedback rendering
# --------------------------------------------------------------------------


def render_feedback(arm: str, cycle_log: list[dict]) -> str:
    """Build the system message for a given arm from the completed cycles."""
    if arm == "base" or not cycle_log:
        return SYSTEM_BASE
    lines = []
    for c in cycle_log:
        k = c["cycle"]
        if arm == "speed":
            lines.append(f"- 第{k}周期：你的生成速度约为 {c['tps']:.1f} token/秒。")
        elif arm == "speed_count":
            lines.append(
                f"- 第{k}周期：你生成了约 {c['out_tokens']} 个 token，"
                f"生成速度约为 {c['tps']:.1f} token/秒。"
            )
        elif arm == "elapsed":
            lines.append(f"- 第{k}周期：你这一轮从开始到结束共耗时约 {c['duration_s']:.1f} 秒。")
        elif arm == "speed_cum":
            lines.append(
                f"- 截至第{k}周期：你的累计平均生成速度约为 {c['cum_tps']:.1f} token/秒。"
            )
        else:
            raise ValueError(f"unknown arm {arm}")
    return SYSTEM_BASE + "\n\n" + FEEDBACK_HEADER + "\n" + "\n".join(lines)


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")

# marker -> the answer always follows the marker; parsing the first number of
# the whole answer is unsafe because the task body itself may contain digits.
MARKERS = {
    "pre_estimate": "预计耗时",
    "prev_duration": "回复耗时秒数",
    "elapsed_since_start": "已过秒数",
}


def parse_seconds(text: str, marker: str | None = None) -> float | None:
    """Extract a seconds value.

    Priority: marker section -> whole-text-is-a-number -> last number in text.
    """
    if not text:
        return None
    t = text.replace(",", "").replace("，", "").replace("：", ":").replace("：", ":")
    if marker:
        m = re.search(re.escape(marker) + r"\s*[:：]?\s*(\d+(?:\.\d+)?)", t)
        if m:
            return float(m.group(1))
    # whole text is basically one number
    stripped = t.strip()
    m = re.fullmatch(r"[^0-9]{0,4}(\d+(?:\.\d+)?)\s*[^0-9]{0,4}", stripped)
    if m:
        val = float(m.group(1))
        return val * 60 if ("分钟" in t and "秒" not in t) else val
    nums = _NUM_RE.findall(t)
    if nums:
        val = float(nums[-1])
        return val * 60 if ("分钟" in t and "秒" not in t) else val
    return None


def parse_json_obj(text: str) -> dict:
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}
