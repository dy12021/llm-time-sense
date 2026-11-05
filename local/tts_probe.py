# -*- coding: utf-8 -*-
"""TTS 读音自检：合成候选说法，用来核对旁白里关键术语/数字是否念对。

用法：
    python local\\tts_probe.py --texts probe.json --outdir out\\voice\\_probe
probe.json：["要念的句子", ...] 或 [{"id": "x", "text": "..."}, ...]

原理：同一 TTS 引擎合成 → 转写回来 → 对比。
不依赖仓库里的旁白，随时可跑。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tts import tts  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts", required=True, help="JSON 数组：字符串或 {id,text}")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--voice", default="Chinese (Mandarin)_Warm_Girl")
    ap.add_argument("--speed", type=float, default=1.0)
    args = ap.parse_args()

    items = json.load(open(args.texts, encoding="utf-8"))
    if isinstance(items, dict):
        items = [{"id": k, "text": v} for k, v in items.items()]
    os.makedirs(args.outdir, exist_ok=True)

    for i, it in enumerate(items):
        if isinstance(it, str):
            it = {"id": f"c{i:02d}", "text": it}
        out = os.path.join(args.outdir, it["id"] + ".mp3")
        if os.path.exists(out) and os.path.getsize(out) > 1000:
            print(f"  skip {it['id']} (已存在)")
            continue
        msg = tts(it["text"], out, voice_id=args.voice, speed=args.speed)
        print(f"  {it['id']}: {msg}", flush=True)
        print(f"      文本：{it['text']}", flush=True)


if __name__ == "__main__":
    main()