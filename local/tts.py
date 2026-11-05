# -*- coding: utf-8 -*-
"""MiniMax TTS 旁白生成（走自有 Key，不走平台代理额度）。

端点：POST https://api.minimax.cn/v1/t2a_v2
模型：speech-02-hd
返回：data.audio 是 **hex 字符串**，需要 unhexlify 成二进制音频。

用法：
    python local/tts.py --text "要念的句子" --out out/voice/seg01.mp3
    python local/tts.py --script out/voice/script.json --outdir out/voice
"""
from __future__ import annotations

import argparse
import binascii
import json
import os
import sys
import time
import tomllib
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

CFG = os.environ.get("MINIMAX_CONFIG", "")
BASE = "https://api.minimax.cn/v1"
MODEL = "speech-02-hd"


def load_key() -> str:
    with open(CFG, "rb") as f:
        cfg = tomllib.load(f)
    return cfg["llm"]["api_key"]


def tts(text: str, out_path: str, voice_id: str = "Chinese (Mandarin)_Warm_Girl",
        speed: float = 1.0, model: str = MODEL, retries: int = 3) -> str:
    key = load_key()
    body = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": {"voice_id": voice_id, "speed": speed, "vol": 1.0, "pitch": 0},
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3",
                          "channel": 1},
        "output_format": "hex",
    }
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            f"{BASE}/t2a_v2",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            print(f"  HTTP {e.code}: {detail}", flush=True)
            if attempt < retries:
                time.sleep(3 * attempt)
                continue
            raise
        except Exception as e:
            print(f"  {type(e).__name__}: {e}", flush=True)
            if attempt < retries:
                time.sleep(3 * attempt)
                continue
            raise
        status = obj.get("base_resp") or {}
        if status.get("status_code") not in (0, None):
            print(f"  api error: {status}", flush=True)
            if attempt < retries:
                time.sleep(3 * attempt)
                continue
            raise RuntimeError(str(status))
        hexdata = (obj.get("data") or {}).get("audio") or ""
        if not hexdata:
            print("  空音频", flush=True)
            if attempt < retries:
                time.sleep(2)
                continue
            raise RuntimeError("空音频")
        data = binascii.unhexlify(hexdata)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        extra = (obj.get("extra_info") or {})
        return (f"ok {len(data)} bytes "
                f"({extra.get('audio_length', 0)/1000:.1f}s, "
                f"usage={extra.get('usage', {})})")
    raise RuntimeError("TTS 失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--script", help="JSON: [{id, text}, ...]")
    ap.add_argument("--out")
    ap.add_argument("--outdir")
    ap.add_argument("--voice", default="Chinese (Mandarin)_Warm_Girl")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--force", action="store_true",
                    help="已存在的音频也重新合成（覆盖写，不删文件）")
    ap.add_argument("--only", default="",
                    help="逗号分隔的段 id，只处理这些段（配合 --force 使用）")
    args = ap.parse_args()

    if args.script:
        items = json.load(open(args.script, encoding="utf-8"))
        outdir = args.outdir or "out/voice"
        os.makedirs(outdir, exist_ok=True)
        only = {s.strip() for s in args.only.split(",") if s.strip()}
        for it in items:
            if only and it["id"] not in only:
                continue
            out = os.path.join(outdir, f"{it['id']}.mp3")
            if (not args.force and os.path.exists(out)
                    and os.path.getsize(out) > 1000):
                print(f"  skip {it['id']} (已存在)")
                continue
            msg = tts(it["text"], out, voice_id=args.voice, speed=args.speed,
                      model=args.model)
            print(f"  {it['id']}: {msg}", flush=True)
    else:
        msg = tts(args.text, args.out, voice_id=args.voice, speed=args.speed,
                  model=args.model)
        print(f"  {args.out}: {msg}")


if __name__ == "__main__":
    main()
