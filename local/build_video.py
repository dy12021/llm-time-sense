# -*- coding: utf-8 -*-
"""把卡片 PNG + 演示录屏 + TTS 旁白合成成一条 MP4。

清单（local/video_manifest.json）：
{
  "segments": [
    {"id": "title", "kind": "card",  "image": "out/video/cards/title.png", "audio": "out/voice/title.mp3"},
    {"id": "demo1", "kind": "video", "src": "out/video/demo.mp4", "start": 0, "duration": 24,
     "audio": "out/voice/demo1.mp3"}
  ]
}

所有片段统一成 1920×1080@30fps、H.264 + AAC，再按清单顺序 concat。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import shutil

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("FFPROBE") or shutil.which("ffprobe") or "ffprobe"
WORK = os.path.join(ROOT, "out", "video")
CLIPS = os.path.join(WORK, "clips")
W, H, FPS = 1920, 1080, 30


def run(cmd: list[str], label: str = "") -> None:
    if label:
        print(f"  · {label}", flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print((p.stderr or "")[-2500:], flush=True)
        raise SystemExit(f"ffmpeg 失败：{label or cmd[:3]}")


def probe_dur(path: str) -> float:
    p = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return float(p.stdout.strip())
    except Exception:
        return 0.0


def main():
    manifest = json.load(open(os.path.join(ROOT, "local", "video_manifest.json"),
                              encoding="utf-8"))
    os.makedirs(CLIPS, exist_ok=True)
    clip_paths = []

    for seg in manifest["segments"]:
        sid = seg["id"]
        audio = seg.get("audio")
        out = os.path.join(CLIPS, f"{sid}.mp4")
        adur = probe_dur(audio) if audio and os.path.exists(audio) else 0.0
        if not adur:
            raise SystemExit(f"片段 {sid} 缺少旁白音频：{audio}")

        if seg["kind"] == "card":
            dur = seg.get("duration") or adur
            run([FFMPEG, "-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}",
                 "-i", seg["image"], "-i", audio,
                 "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                 "-pix_fmt", "yuv420p", "-r", str(FPS),
                 "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
                 out], f"card {sid} ({dur:.1f}s)")
        else:
            start = seg.get("start", 0)
            dur = seg.get("duration") or adur
            run([FFMPEG, "-y", "-ss", f"{start}", "-t", f"{dur:.3f}", "-i", seg["src"],
                 "-i", audio,
                 "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0D111C",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                 "-pix_fmt", "yuv420p", "-r", str(FPS),
                 "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
                 out], f"video {sid} @{start}s ({dur:.1f}s)")
        clip_paths.append(out)

    list_txt = os.path.join(WORK, "concat.txt")
    with open(list_txt, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write("file '" + p.replace("\\", "/").replace("'", "'\\''") + "'\n")

    final = os.path.join(WORK, "final.mp4")
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", list_txt,
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", final], "concat")
    print(f"\n完成：{final}  时长 {probe_dur(final):.1f}s  "
          f"大小 {os.path.getsize(final)/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
