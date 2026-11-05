# -*- coding: utf-8 -*-
"""开源前脱敏扫描：命中 0 条才算干净。

扫的是整个仓库（含 raw/ 原始记录与报告），不只扫代码。
规则：
  1. 各类密钥形态（OpenAI sk-、JWT、Bearer、常量赋值里的 key/token/secret）
  2. 绝对本机路径（C:\\Users\\... / D:\\coding\\...）
  3. 私有网段 IP（127.0.0.1 与 0.0.0.0 除外）
  4. 邮箱地址
  5. 私有数据目录（.db / data/ 等不该进远端的东西）

用法：
    python scripts\\scan_sensitive.py            # 扫全仓
    python scripts\\scan_sensitive.py --staged   # 只扫 git 已跟踪的文件
退出码：有命中 = 1。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "_work",
             "frames", "_chromeprof", ".pytest_cache"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mp3", ".wav", ".ico",
            ".woff", ".woff2", ".ttf", ".pyc", ".zip", ".exe", ".pdf"}
BIN_HINT = 8192

RULES: list[tuple[str, str, str]] = [
    ("openai-key", r"\bsk-[A-Za-z0-9_\-]{16,}", "OpenAI 风格密钥"),
    ("jwt", r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", "JWT"),
    ("bearer", r"\bBearer\s+[A-Za-z0-9_\-\.]{20,}", "硬编码 Bearer 令牌"),
    ("secret-assign", r"(?i)\b(api[_-]?key|secret|password|passwd|access[_-]?token|"
                      r"auth[_-]?token)\b\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']",
     "疑似硬编码凭据"),
    ("minimax-key", r"\bsk-[A-Za-z0-9]{40,}\b", "疑似长随机串凭据"),
    ("abs-path", r"(?i)\b[A-Z]:\\(?:Users|coding)\\", "绝对本机路径"),
    ("home-path", r"(?i)\b(?:/home/|/Users/)[A-Za-z0-9_\-]+/", "家目录绝对路径"),
    ("private-ip", r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\."
                    r"\d{1,3}\.\d{1,3}\b", "私有网段 IP"),
    ("email", r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "邮箱地址"),
    ("db-file", r"(?i)\b[\w\-]+\.(?:db|sqlite3?)\b", "疑似本地数据库文件"),
]


def iter_files(staged: bool):
    if staged:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8")
        for rel in out.stdout.splitlines():
            p = os.path.join(ROOT, rel)
            if os.path.isfile(p):
                yield rel, p
        return
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXT:
                continue
            if any(part in SKIP_DIRS for part in os.path.relpath(p, ROOT).split(os.sep)):
                continue
            try:
                if os.path.getsize(p) > 4 * 1024 * 1024:
                    continue
            except OSError:
                continue
            yield os.path.relpath(p, ROOT), p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true", help="只扫 git 已跟踪文件")
    args = ap.parse_args()

    hits = []
    nfiles = 0
    for rel, p in iter_files(args.staged):
        try:
            raw = open(p, "rb").read()
        except OSError:
            continue
        if b"\x00" in raw[:BIN_HINT]:
            continue  # 二进制
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        nfiles += 1
        for i, line in enumerate(text.splitlines(), 1):
            for name, pat, why in RULES:
                for m in re.finditer(pat, line):
                    frag = m.group(0)
                    if name == "minimax-key" and not re.fullmatch(
                            r"sk-[A-Za-z0-9]{40,}", frag):
                        continue
                    hits.append((rel, i, name, why, frag[:60]))

    print(f"扫描 {nfiles} 个文件")
    if not hits:
        print("0 命中 —— 干净 ✅")
        return 0
    print(f"\n{len(hits)} 处命中：")
    seen = set()
    for rel, i, name, why, frag in hits:
        key = (rel, name, frag)
        if key in seen:
            continue
        seen.add(key)
        print(f"  {rel}:{i}  [{name}] {why}  →  {frag}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
