# -*- coding: utf-8 -*-
"""L2 事后/事前预估的「有没有真的用速率」判定。

比中位数干净得多的指标：**模型在思维链里有没有拿注入的速率做除法**。
判定方式：思维链里出现了注入速率的数字（如 158.5）→ 用了。

顺带把每轮的「计划 token 数 × 速率」推回去，看它是不是真的在估长度。
"""
from __future__ import annotations

import json
import os
import re
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")


def used_rate(reasoning: str, rate: float | None) -> bool:
    if not reasoning or not rate:
        return False
    txt = reasoning.replace(",", "")
    # 速率可能写成 158.5 / 159 / 158
    for form in (f"{rate:.1f}", f"{rate:.0f}", f"{rate:.2f}"):
        if form in txt:
            return True
    return False


def division_hint(reasoning: str) -> str | None:
    """抓思维链里最像「除法算时间」的那一句。"""
    if not reasoning:
        return None
    for s in re.split(r"[。\n]", reasoning):
        s = s.strip()
        if ("/" in s and ("second" in s or "秒" in s)) or ("≈" in s and "second" in s):
            return s
    return None


def main():
    for name in ("local_pre", "local_posthoc"):
        path = os.path.join(RAW, name + ".jsonl")
        if not os.path.exists(path):
            continue
        recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        by_arm = {}
        for r in recs:
            arm = r["arm"]
            rate = r.get("injected_rate")
            if arm == "speed":
                rate = r.get("injected_rate")
            reason = (r.get("metrics") or {}).get("reasoning") or ""
            if name == "local_posthoc":
                reason = (r.get("probe_metrics") or {}).get("reasoning") or ""
            by_arm.setdefault(arm, []).append({
                "rep": r["rep"],
                "rate": rate,
                "used_rate": used_rate(reason, rate),
                "hint": division_hint(reason),
                "est": r.get("est_s"),
            })
        print(f"===== {name} =====")
        for arm, rows in by_arm.items():
            n = len(rows)
            k = sum(1 for x in rows if x["used_rate"])
            ests = [x["est"] for x in rows if x["est"]]
            print(f"  {arm:12s} n={n:2d}  思维链里用到注入速率: {k}/{n}")
            for x in rows:
                print(f"      rep{x['rep']} rate={x['rate']} used={x['used_rate']} "
                      f"est={x['est']}  hint={(x['hint'] or '')[:110]}")
        print()


if __name__ == "__main__":
    main()
