# -*- coding: utf-8 -*-
"""生成视频合成计划：每段旁白时长 + 段间留白 = 该段画面总长。

时长用「解码后的 PCM 实际长度」，不用 ffprobe 报的容器时长 ——
mp3 容器时长含编码填充，每段虚高约 0.17s，9 段累计音画漂移 1.5s。
输出：out/video/plan.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
import shutil

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
VDIR = os.path.join(OUT, "voice")
BIN = os.path.dirname(shutil.which("ffmpeg") or "")
FFPROBE = os.environ.get("FFPROBE") or shutil.which("ffprobe") or "ffprobe"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"

GAP = 0.35          # 段间留白（秒）
REVEAL = 2.70       # 每段开头的「淡入过程」占多长（秒）


def probe(p: str) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", p], capture_output=True, text=True)
    return float(out.stdout.strip())


def decoded_dur(p: str) -> float:
    """mp3 容器时长含编码填充，解码后更短 —— 排期必须用解码后的实际长度。"""
    tmp = os.path.join(VDIR, "_tmp_decode.wav")
    subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
         "-i", p, "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", tmp],
        capture_output=True, text=True)
    try:
        with wave.open(tmp, "rb") as fh:
            return fh.getnframes() / float(fh.getframerate())
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main():
    segs = json.load(open(os.path.join(ROOT, "local", "voice_script.json"),
                          encoding="utf-8"))
    plan = []
    for i, s in enumerate(segs):
        mp3 = os.path.join(VDIR, s["id"] + ".mp3")
        if not os.path.exists(mp3):
            raise SystemExit(f"缺旁白音频: {mp3}")
        container = round(probe(mp3), 3)
        d = round(decoded_dur(mp3), 3)
        gap = 0.0 if i == len(segs) - 1 else GAP
        clip = round(d + gap, 3)
        plan.append({
            "idx": i, "sec": i + 1, "id": s["id"], "mp3": mp3,
            "container_dur": container, "voice_dur": d, "gap": gap,
            "clip_dur": clip, "still_dur": round(clip - REVEAL, 3),
        })
    total_voice = round(sum(p["voice_dur"] for p in plan), 3)
    total_clip = round(sum(p["clip_dur"] for p in plan), 3)
    out = {"plan": plan, "total_voice": total_voice,
           "total_clip": total_clip, "reveal": REVEAL, "gap": GAP}
    dst = os.path.join(OUT, "video", "plan.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"plan -> {dst}")
    for p in plan:
        print(f"  s{p['sec']}: 容器 {p['container_dur']:6.2f}s  解码 {p['voice_dur']:6.2f}s"
              f"  画面 {p['clip_dur']:6.2f}s")
    print(f"  合计：语音 {total_voice:.2f}s / 画面 {total_clip:.2f}s")


if __name__ == "__main__":
    main()
