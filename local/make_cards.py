# -*- coding: utf-8 -*-
"""生成视频用的信息卡片（1920×1080 PNG）。

深色科技风：左下角标题 + 右侧关键数字大字。字体用微软雅黑
（msyh.ttc / msyhbd.ttc），本机已确认存在。
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD_DIR = os.path.join(ROOT, "out", "video", "cards")
W, H = 1920, 1080

FONT_REG = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

BG_TOP = (13, 17, 28)
BG_BOTTOM = (22, 28, 46)
ACCENT = (94, 234, 212)        # 青
ACCENT2 = (255, 196, 87)       # 琥珀
TEXT = (236, 240, 248)
MUTED = (146, 158, 180)


def gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), BG_TOP)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        d.line([(0, y), (w, y)],
               fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)))
    return img


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=fnt) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def make_card(path: str, *, kicker: str = "", title: str = "", subtitle: str = "",
              bullets: list[str] | None = None, big: tuple[str, str] | None = None,
              accent: tuple[int, int, int] = ACCENT) -> None:
    img = gradient(W, H)
    d = ImageDraw.Draw(img, "RGBA")

    # 顶部装饰条
    d.rectangle([0, 0, 18, H], fill=accent + (255,))
    # 网格感背景
    for gx in range(0, W, 96):
        d.line([(gx, 0), (gx, H)], fill=(255, 255, 255, 6))
    for gy in range(0, H, 96):
        d.line([(0, gy), (W, gy)], fill=(255, 255, 255, 6))

    y = 150
    if kicker:
        d.text((120, y), kicker, font=font(FONT_BOLD, 40), fill=accent)
        y += 80
    if title:
        for ln in wrap(d, title, font(FONT_BOLD, 92), W - 320):
            d.text((120, y), ln, font=font(FONT_BOLD, 92), fill=TEXT)
            y += 116
        y += 24
    if subtitle:
        for ln in wrap(d, subtitle, font(FONT_REG, 40), 1080):
            d.text((120, y), ln, font=font(FONT_REG, 40), fill=MUTED)
            y += 58

    if bullets:
        y += 30
        for b in bullets:
            d.ellipse([126, y + 18, 140, y + 32], fill=accent)
            for i, ln in enumerate(wrap(d, b, font(FONT_REG, 38), 1000)):
                d.text((168, y), ln, font=font(FONT_REG, 38), fill=TEXT)
                y += 54 if i == 0 else 0
            y += 22

    if big:
        val, unit = big
        bx, by = 1240, 470
        d.text((bx, by), val, font=font(FONT_BOLD, 190), fill=accent)
        wv = d.textlength(val, font=font(FONT_BOLD, 190))
        d.text((bx + wv + 18, by + 120), unit, font=font(FONT_BOLD, 52), fill=MUTED)

    d.text((120, H - 78), "LLM 时间感实验 · 本地 LM Studio / google/gemma-4-e2b",
           font=font(FONT_REG, 26), fill=(120, 132, 154))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print(f"card -> {path}")


def main():
    os.makedirs(CARD_DIR, exist_ok=True)
    spec_path = os.path.join(ROOT, "local", "cards.json")
    spec = json.load(open(spec_path, encoding="utf-8"))
    for card in spec:
        make_card(
            os.path.join(CARD_DIR, card["id"] + ".png"),
            kicker=card.get("kicker", ""),
            title=card.get("title", ""),
            subtitle=card.get("subtitle", ""),
            bullets=card.get("bullets"),
            big=tuple(card["big"]) if card.get("big") else None,
            accent=tuple(card.get("accent", ACCENT)) if card.get("accent") else ACCENT,
        )


if __name__ == "__main__":
    main()
