# -*- coding: utf-8 -*-
"""音频响度标准化（EBU R128：I=-16 LUFS, TP=-1.5 dBTP）。

两遍法：先测 loudnorm 的 measured_* 参数，再带着测量值线性归一化重出成片。
直接读 _work/silent.mp4 + _work/audio.wav 重 mux，覆盖 final.mp4（不删任何文件）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import shutil

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VDIR = os.path.join(ROOT, "out", "video")
WORK = os.path.join(VDIR, "_work")
BIN = os.path.dirname(shutil.which("ffmpeg") or "")
FF = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"


def run(args):
    p = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p


def main():
    silent = os.path.join(WORK, "silent.mp4")
    audio = os.path.join(WORK, "audio.wav")
    final = os.path.join(VDIR, "final.mp4")
    I, TP, LRA = -16.0, -1.5, 11.0

    # --- 第一遍：测量 ---
    p = run([FF, "-hide_banner", "-nostats", "-i", audio,
             "-af", f"loudnorm=I={I}:TP={TP}:LRA={LRA}:print_format=json",
             "-f", "null", "NUL"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if not m:
        raise SystemExit("loudnorm 测量失败:\n" + p.stderr[-2000:])
    meas = json.loads(m.group(0))
    print("measured:", {k: meas[k] for k in
                        ("input_i", "input_tp", "input_lra", "input_thresh")})

    # --- 第二遍：线性归一化 + 重 mux ---
    af = (f"loudnorm=I={I}:TP={TP}:LRA={LRA}:"
          f"measured_I={meas['input_i']}:"
          f"measured_TP={meas['input_tp']}:"
          f"measured_LRA={meas['input_lra']}:"
          f"measured_thresh={meas['input_thresh']}:"
          f"offset={meas['target_offset']}:linear=true")
    p = run([FF, "-y", "-hide_banner", "-loglevel", "error",
             "-i", silent, "-i", audio,
             "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "copy", "-af", af,
             "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
             "-shortest", "-movflags", "+faststart", final])
    if p.returncode != 0:
        raise SystemExit("重 mux 失败:\n" + p.stderr[-3000:])

    # --- 复测 ---
    p = run([FF, "-hide_banner", "-nostats", "-i", final,
             "-af", "volumedetect", "-f", "null", "NUL"])
    for line in p.stderr.splitlines():
        if "mean_volume" in line or "max_volume" in line:
            print(line.strip())
    print(f"size = {os.path.getsize(final) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
