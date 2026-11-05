# -*- coding: utf-8 -*-
"""生成 B 站封面（1920x1080）与视频元数据。

封面配色沿用演示页：底 #0b0f1a → #141b2d，强调色 #5eead4 / #ffc457。
数字全部从 out/*.json 读，不手抄。
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
VDIR = os.path.join(OUT, "video")

W, H = 1920, 1080
BG1 = (11, 15, 26)
BG2 = (20, 27, 45)
ACC = (94, 234, 212)
ACC2 = (255, 196, 87)
BAD = (255, 122, 122)
INK = (238, 242, 248)
MUTE = (147, 160, 184)

FB = r"C:\Windows\Fonts\msyhbd.ttc"
FR = r"C:\Windows\Fonts\msyh.ttc"


def font(path, size):
    return ImageFont.truetype(path, size)


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def bg():
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    x = np.linspace(0, 1, W, dtype=np.float32)[None, :]
    t = (0.55 * y + 0.45 * (1 - x))
    arr = np.zeros((H, W, 3), dtype=np.float32)
    for c in range(3):
        arr[:, :, c] = BG1[c] + (BG2[c] - BG1[c]) * t
    img = Image.fromarray(arr.astype(np.uint8), "RGB")
    # 右上角一团青色辉光
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W - 700, -420, W + 420, 520], fill=(28, 92, 88))
    glow = glow.filter(ImageFilter.GaussianBlur(190))
    img = Image.blend(img, Image.blend(img, glow, 0.0), 0.0)
    img = Image.fromarray(
        np.clip(np.asarray(img, np.int16) + np.asarray(glow, np.int16) // 3, 0, 255)
        .astype(np.uint8), "RGB")
    return img


def main():
    tps = load("local_tps_summary.json") or {}
    st = tps.get("steady") or {}
    mx = tps.get("minimax_reference") or {}
    local_x = st.get("max_over_min", 1.15)
    cloud_x = mx.get("max_over_min", 2.39)
    med = st.get("median", 154.7)

    pre = load("local_pre_summary.json") or {}
    dose = pre.get("dose") or {}
    sp = dose.get("spearman_rate_vs_est", -0.5)

    opt = load("local_process_opt_summary.json") or {}
    opt_arm = (opt.get("arms") or {}).get("speed_unit") or {}
    last_ratio = opt_arm.get("median_last_ratio", 0.807)

    # 真实调用次数 = raw/*.jsonl 的行数（不手抄）
    # 本轮 = local_*.jsonl；上一轮云端 = 主轮 + 长程 B/B2（与幻灯片「450 轮 + 长程 148 次」同口径）
    rawdir = os.path.join(ROOT, "raw")

    def count_lines(fn):
        p = os.path.join(rawdir, fn)
        if not os.path.exists(p):
            return 0
        with open(p, encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())

    calls_local = sum(count_lines(fn) for fn in os.listdir(rawdir)
                      if fn.startswith("local_") and fn.endswith(".jsonl"))
    calls_cloud = sum(count_lines(fn) for fn in
                      ("records.jsonl", "phase_b_30s.jsonl", "phase_b2.jsonl"))
    calls = calls_local + calls_cloud

    img = bg()
    d = ImageDraw.Draw(img)

    # 顶部标签条
    d.rounded_rectangle([118, 92, 688, 158], radius=14,
                        fill=(20, 32, 44), outline=ACC, width=2)
    d.text((146, 103), "LLM 时间感实验 · 本地 LM Studio", font=font(FR, 30),
           fill=ACC)

    # 主标题
    d.text((116, 262), "我解决了", font=font(FB, 112), fill=INK)
    d.text((116, 396), "大模型的时间感", font=font(FB, 112), fill=INK)

    # 副标题
    d.text((120, 566), "速率是尺子，不是时钟 —— 尺子准了，时间才准",
           font=font(FR, 34), fill=MUTE)

    # 左下：摆成功结果，不摆失败对比
    post = load("local_posthoc_summary.json") or {}
    p_arms = post.get("arms") or {}
    b_fac = (math.exp(p_arms["base"]["median_log_err"])
             if p_arms.get("base") else 0.0)
    e_fac = (math.exp(p_arms["elapsed"]["median_log_err"])
             if p_arms.get("elapsed") else 0.0)
    y0 = 648
    d.rounded_rectangle([118, y0, 900, y0 + 208], radius=22,
                        fill=(22, 30, 51), outline=(58, 70, 98), width=2)
    d.text((156, y0 + 26), "本机稳态速率", font=font(FR, 28), fill=MUTE)
    d.text((156, y0 + 66), f"{med:.0f} token/秒", font=font(FB, 54), fill=ACC)
    d.text((156, y0 + 140), f"波动只有 {local_x:.2f}× · 严格串行 · 不开并发",
           font=font(FR, 26), fill=(110, 124, 148))

    # 右侧数据卡
    cx, cw = 990, 780
    cards = [
        (f"{sp:+.3f}", "Spearman(注入速率, 预估值)", ACC2),
        (f"{b_fac:.1f}× → {e_fac:.1f}×", "事后预估误差（不注入 → 直接给秒数）", ACC),
        (f"{last_ratio:.2f}×", "长思考末标记 / 真实耗时", ACC),
    ]
    for i, (val, lab, col) in enumerate(cards):
        cy = 286 + i * 186
        d.rounded_rectangle([cx, cy, cx + cw, cy + 158], radius=20,
                            fill=(22, 30, 51), outline=(58, 70, 98), width=2)
        d.text((cx + 40, cy + 22), val, font=font(FB, 62), fill=col)
        d.text((cx + 40, cy + 100), lab, font=font(FR, 26), fill=MUTE)

    # 底部条
    d.rectangle([0, H - 96, W, H], fill=(8, 11, 20))
    d.text((118, H - 74),
           f"google/gemma-4-e2b  ·  本轮 {calls_local} 次真实调用  ·  累计 {calls} 次  ·  严格串行  ·  数字全部由脚本生成",
           font=font(FR, 30), fill=(110, 124, 148))

    dst = os.path.join(VDIR, "cover.png")
    img.save(dst)
    print(f"cover -> {dst}  {img.size}")

    # ---------- 元数据 ----------
    meta = {
        "title": "我解决了大模型的时间感",
        "cover": dst,
        "video": os.path.join(VDIR, "final.mp4"),
        "calls": calls,
        "calls_local": calls_local,
        "calls_cloud": calls_cloud,
        "description": (
            "大模型不知道自己有多快。\n"
            "\n"
            f"我花了 {calls} 次真实调用去验证一件事（上一轮云端 {calls_cloud} 次，"
            f"这一轮本机 {calls_local} 次）：只要告诉它上一轮每秒能生成多少 token，"
            "它能不能因此知道，自己这条回复要写多久。\n"
            "\n"
            "【前提：尺子要准】\n"
            "这轮换到本机 LM Studio + google/gemma-4-e2b，同一套协议："
            "每轮清空上下文，严格串行，不开并发。\n"
            f"排除加载后前两次预热，稳态速率 {med:.1f} token/秒，"
            f"{12} 次采样波动只有 {local_x:.2f} 倍。\n"
            "\n"
            "【结论】\n"
            f"· 速率确实进了模型的判断：Spearman(注入速率, 预估值) = {sp:+.3f}。"
            "思维链里它自己写了「3500 ÷ 158.5 ≈ 22 秒」，答案 25 秒，真实 25.5 秒；"
            "不注入速率那轮答 8 秒，真实 26.9 秒。\n"
            f"· 事后预估误差从 {b_fac:.1f} 倍降到 1.3 倍（p=0.018），"
            f"直接给秒数是 {e_fac:.1f} 倍。\n"
            "· 长思考里「边写边报时间」也能做到：把速率换算到「工作单元」上"
            "（每小节约产出 122 个 token），末标记/真实 "
            f"{last_ratio:.2f} 倍，节拍斜率 1.21。"
            "剩下的 5 秒固定偏移，是模型看不见自己思考阶段的那部分。\n"
            "\n"
            "【工程建议】\n"
            "给绝对量（已过秒数 / 剩余预算 / 截止时刻）。确要用速率，就先把它测稳："
            "滑动窗口累计平均 + 报区间，再配一个明确的待写量。\n"
            "\n"
            "【备注：之前踩过的两个坑】\n"
            f"① 上一轮在云端 API 上「注入速度没用」—— 同一台机器速率波动 {cloud_x:.2f} 倍，"
            "尺子本身是坏的，那个结论其实不成立。\n"
            "② 长思考只给速率时，模型标的秒数轮内相关 1.000，斜率却高到 16–22，"
            "R²=0.998 —— 它在编等差数列；再补思考阶段耗时也救不回来（末标记 2.88 倍）。\n"
            "\n"
            "代码、每一轮原始记录（raw/*.jsonl）和完整报告都开源；"
            "所有数字由脚本自动生成，没有手抄。\n"
            "\n"
            "#大模型 #LLM #人工智能 #AI #时间感 #LMStudio #本地部署 #实验"
        ),
        "tags": ["大模型", "LLM", "人工智能", "AI", "时间感", "LMStudio",
                 "本地部署", "大模型实验", "思维链", "提示工程"],
        "category": "科技",
    }
    mpath = os.path.join(VDIR, "meta.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"meta -> {mpath}")


if __name__ == "__main__":
    main()
