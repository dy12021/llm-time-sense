# -*- coding: utf-8 -*-
"""把 9 段的首张成品帧拼成 3x3 联络表，方便一次性目检。"""
from __future__ import annotations

import os
import sys

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FDIR = os.path.join(ROOT, "out", "video", "frames")
DST = os.path.join(ROOT, "out", "video", "contact_sheet.png")

COLS, ROWS = 3, 3
TW, TH = 620, 349  # 缩略图尺寸（16:9）
PAD = 10
LAB = 26

canvas = Image.new("RGB", (COLS * TW + PAD * (COLS + 1),
                           ROWS * (TH + LAB) + PAD * (ROWS + 1)),
                   (10, 14, 24))
try:
    from PIL import ImageFont
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 18)
except Exception:
    font = None

for i in range(9):
    p = os.path.join(FDIR, f"s{i + 1:02d}_f07.png")
    if not os.path.exists(p):
        continue
    im = Image.open(p).convert("RGB").resize((TW, TH), Image.LANCZOS)
    cx = PAD + (i % COLS) * (TW + PAD)
    cy = PAD + (i // COLS) * (TH + LAB + PAD)
    canvas.paste(im, (cx, cy))
    if font:
        from PIL import ImageDraw
        ImageDraw.Draw(canvas).text((cx + 4, cy + TH + 2), f"sec {i + 1}",
                                    fill=(120, 230, 212), font=font)

canvas.save(DST)
print(f"contact sheet -> {DST}  {canvas.size}")
