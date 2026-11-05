# -*- coding: utf-8 -*-
"""把 meta.json 渲染成一份可直接照抄的投稿物料清单（标题/简介/标签/封面）。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
VDIR = os.path.join(ROOT, "out", "video")

meta = json.load(open(os.path.join(VDIR, "meta.json"), encoding="utf-8"))
video = os.path.join(VDIR, "final.mp4")
cover = os.path.join(VDIR, "cover.png")
dst = os.path.join(VDIR, "投稿物料.md")

FFPROBE = os.environ.get("FFPROBE") or shutil.which("ffprobe") or "ffprobe"


def probe_duration(path):
    """从成片里探测真实时长（不手抄）。"""
    if not os.path.exists(path):
        return 0.0
    p = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


size_mb = os.path.getsize(video) / 1e6 if os.path.exists(video) else 0
dur = probe_duration(video)


def rel(path):
    """仓库相对路径，统一用正斜杠（跨平台可读，且不含本机绝对路径）。"""
    return os.path.relpath(path, ROOT).replace(os.sep, "/")

lines = [
    "# B 站投稿物料",
    "",
    "## 标题",
    "",
    f"```\n{meta['title']}\n```",
    "",
    "## 简介（直接复制）",
    "",
    "```text",
    meta["description"],
    "```",
    "",
    "## 标签",
    "",
    "```",
    "，".join(meta["tags"]),
    "```",
    "",
    "## 分区 / 封面 / 文件",
    "",
    f"- 分区建议：{meta['category']}",
    f"- 视频文件：`{rel(video)}`（1920×1080，{dur:.1f} 秒，{size_mb:.1f} MB，H.264 + AAC）",
    f"- 封面文件：`{rel(cover)}`（1920×1080 PNG，B 站封面比例刚好 16:9）",
    "- 幻灯片（视频同款，自包含单文件）："
    f"`{rel(os.path.join(VDIR, 'demo.html'))}`",
    "（以上路径均相对于仓库根目录，用正斜杠）",
    "",
    "## 发布后",
    "",
    "仓库已推送（public）：`github.com/dy12021/llm-time-sense` —— "
    "视频最后一页印的就是这个地址。",
    "",
]

with open(dst, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"投稿物料 -> {dst}")
