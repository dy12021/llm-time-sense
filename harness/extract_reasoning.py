# -*- coding: utf-8 -*-
r"""从 Phase B2 的思维链里抽出「速率→秒数」换算的自述原文。

模型常在 reasoning 里把自己的算式写出来，例如：
    "133 lines maybe 2000 Chinese tokens at 40 tok/sec ~50 sec. Say 70 sec."

这些自述是「模型到底有没有把速率当除数用」的**直接证据**——
比任何统计推断都硬。本脚本把含换算线索的片段抽出来，供报告引用。

匹配线索（任一命中即抓取上下文窗口）：
  速率写法：tok/sec、tok/s、token/秒、tokens per second
  换算写法：\d+\s*(tokens?|字)\b ... \d+\s*sec、/ \d+ .* sec、at \d+ tok
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

PAT = re.compile(
    r"(tok(?:en)?s?/s(?:ec)?|tokens?\s+per\s+second|token/秒)"          # 速率写法
    r"|(?:\d[\d,\.]*\s*(?:tokens?|字|chars?)?[^.;\n]{0,40}?\d[\d,\.]*\s*sec)"
    r"|(?:\d[\d,\.]*\s*(?:tokens?|字)\s*(?:/|÷|div)\s*\d[\d,\.]*)"
    r"|(?:/ ?\d[\d,\.]*\s*tok)",
    re.I)

# 常见的「速率→秒」表述
ALT = re.compile(r"(at\s+\d[\d,\.]*\s*tok|/s\b|\d+\s*tokens?\b[^.]{0,30}\bsec)", re.I)


def snippets(text: str, width: int = 150) -> list[str]:
    if not text:
        return []
    out = []
    t = text.replace("\n", " ")
    for m in PAT.finditer(t):
        s = max(0, m.start() - width // 2)
        e = min(len(t), m.end() + width // 2)
        frag = t[s:e].strip()
        if frag and frag not in out:
            out.append(frag)
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAW, "phase_b2.jsonl")
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    res = []
    print("=" * 96)
    print("Phase B2 思维链里的「速率→秒数」换算自述")
    print("=" * 96)
    for r in recs:
        if r.get("phase") != "B2_A2":
            continue
        rs = snippets(r["metrics"].get("reasoning") or "")
        if not rs:
            continue
        rate = r.get("injected_rate")
        res.append({"arm": r["arm"], "trial": r["trial"],
                    "injected_rate": rate,
                    "estimate_s": r["parsed"].get("estimate_s"),
                    "actual_gen_s": r["metrics"]["gen_s"],
                    "content_tokens": r["metrics"]["content_tokens"],
                    "snippets": rs})
        print(f"[{r['arm']:<10} k{r['trial']}] 注入 {rate if rate else '—'} tok/s | "
              f"预估 {r['parsed'].get('estimate_s')}s | 实测 {r['metrics']['gen_s']:.1f}s | "
              f"正文 {r['metrics']['content_tokens']} tok")
        for s in rs[:2]:
            print(f"    … {s} …")
        print()

    n_rate = sum(1 for x in res if x["injected_rate"])
    n_base = sum(1 for x in res if not x["injected_rate"])
    print(f"含换算自述的试验：注入速率臂 {n_rate} 次、基线臂 {n_base} 次"
          f"（共 {len(res)} 条 A2 记录）")
    dst = os.path.join(OUT, "phase_b2_reasoning.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"n_with_arithmetic": len(res),
                   "n_rate_arm": n_rate, "n_base_arm": n_base,
                   "items": res}, f, ensure_ascii=False, indent=2)
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
