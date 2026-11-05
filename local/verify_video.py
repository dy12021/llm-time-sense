# -*- coding: utf-8 -*-
"""终检 final.mp4：
  1) 按段落中点抽帧拼 3x3 联络表，确认每段画面与旁白对得上
  2) 对比同一段首尾帧，确认 zoompan 慢推真的在动
  3) 打印流信息 + 音频响度
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image
import shutil

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VDIR = os.path.join(ROOT, "out", "video")
FINAL = os.path.join(VDIR, "final.mp4")
BIN = os.path.dirname(shutil.which("ffmpeg") or "")
FF = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("FFPROBE") or shutil.which("ffprobe") or "ffprobe"

TW, TH = 620, 349
PAD, LAB = 10, 26
COLS = 3


def run(args):
    p = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(p.stderr[-2000:])
    return p


def grab(t, name):
    out = os.path.join(VDIR, "_work", name)
    run([FF, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}",
         "-i", FINAL, "-frames:v", "1", out])
    return out


def main():
    plan = json.load(open(os.path.join(VDIR, "plan.json"), encoding="utf-8"))["plan"]
    ROWS = (len(plan) + COLS - 1) // COLS
    canvas = Image.new("RGB", (COLS * TW + PAD * (COLS + 1),
                               ROWS * (TH + LAB) + PAD * (ROWS + 1)), (10, 14, 24))
    from PIL import ImageDraw, ImageFont
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 18)

    t = 0.0
    mids = []
    for seg in plan:
        mid = t + seg["clip_dur"] / 2
        mids.append((seg["sec"], mid))
        t += seg["clip_dur"]

    for i, (sec, mid) in enumerate(mids):
        f = grab(mid, f"vcheck_s{sec:02d}.png")
        im = Image.open(f).convert("RGB").resize((TW, TH), Image.LANCZOS)
        cx = PAD + (i % COLS) * (TW + PAD)
        cy = PAD + (i // COLS) * (TH + LAB + PAD)
        canvas.paste(im, (cx, cy))
        ImageDraw.Draw(canvas).text((cx + 4, cy + TH + 2),
                                    f"sec {sec}  @{mid:.1f}s", fill=(120, 230, 212),
                                    font=font)
    sheet = os.path.join(VDIR, "verify_sheet.png")
    canvas.save(sheet)
    print(f"verify sheet -> {sheet}")

    # --- 慢推是否真的在动：比较第 1 段定格段首尾两帧（时刻由 plan 推，不写死） ---
    first = plan[0]
    t_a = 3.2
    t_b = max(t_a + 1.0, first["clip_dur"] - 0.6)
    a = np.asarray(Image.open(grab(t_a, "zoom_a.png")).convert("L"), np.int16)
    b = np.asarray(Image.open(grab(t_b, "zoom_b.png")).convert("L"), np.int16)
    diff = float(np.abs(a - b).mean())
    print(f"zoompan 检查：sec1 定格段首尾帧（{t_a:.1f}s vs {t_b:.1f}s）平均像素差 = {diff:.3f} "
          f"({'有推进' if diff > 0.5 else '没有推进（异常）'})")

    # --- 流信息 ---
    info = run([FFPROBE, "-v", "error", "-show_entries",
                "stream=codec_name,width,height,r_frame_rate,channels,sample_rate",
                "-show_entries", "format=duration,size,bit_rate",
                "-of", "default=noprint_wrappers=1", FINAL]).stdout
    print(info)

    # --- 音频响度 ---
    lv = run([FF, "-hide_banner", "-nostats", "-i", FINAL, "-af",
              "volumedetect", "-f", "null", "NUL"])
    for line in lv.stderr.splitlines():
        if "mean_volume" in line or "max_volume" in line:
            print(line.strip())


if __name__ == "__main__":
    main()
