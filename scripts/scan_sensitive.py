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
    python scripts\\scan_sensitive.py            # 扫「将要发布的内容」= 已跟踪 + 未跟踪但未被 ignore
    python scripts\\scan_sensitive.py --staged   # 只扫 git 已跟踪文件
退出码：有命中 = 1。

三个曾经踩过的盲区（现已堵上，别再退回去）：
  * git ls-files 默认把非 ASCII 路径转义成八进制，路径拼不出来 → 文件被静默跳过。
    现在统一用 -z 取原始字节。
  * 非 UTF-8 文件（如 UTF-16）直接跳过 → 同样假阴性。
    现在按 BOM/编码逐个尝试解码，且解不开的文件会打印出来，不再静默。
  * 默认模式以前遍历整个目录，会把 gitignore 的草稿也扫进来，
    噪音盖住真问题。现在默认模式 = 跟踪文件 + 未跟踪但未被 ignore 的文件。
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


def git_ls(args: list[str]) -> list[str]:
    """用 -z 取原始路径（git 默认会把非 ASCII 路径转义成八进制，导致文件被静默跳过）。"""
    out = subprocess.run(["git", "ls-files", "-z"] + args, cwd=ROOT, capture_output=True)
    return [x for x in out.stdout.decode("utf-8").split("\0") if x]


def iter_files(staged: bool):
    """返回 (文件列表, 缺失列表)。缺失 = 路径拿到但文件不在，绝不静默丢弃。"""
    files, missing = [], []
    if staged:
        rels = git_ls(["--cached"])
    else:
        # 「将要发布的内容」= 已跟踪 + 未跟踪但未被 ignore
        rels = git_ls(["--cached", "--others", "--exclude-standard"])
    for rel in rels:
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p):
            missing.append(rel)
            continue
        if os.path.splitext(rel)[1].lower() in SKIP_EXT:
            continue  # 媒体/二进制，按设计就是二进制，不算异常
        files.append((rel, p))
    return files, missing


def decode(raw: bytes):
    """返回 (文本, 编码名)；解不了返回 (None, 原因)。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace"), "utf-16"
    if b"\x00" in raw[:BIN_HINT]:
        return None, "binary"
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    if len(raw) % 2 == 0:
        for enc in ("utf-16-le", "utf-16-be"):
            try:
                return raw.decode(enc), enc
            except UnicodeDecodeError:
                continue
    return None, "undecodable"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true", help="只扫 git 已跟踪文件")
    args = ap.parse_args()

    files, missing = iter_files(args.staged)
    hits = []
    enc_count: dict[str, int] = {}
    skipped = []

    for rel, p in files:
        try:
            raw = open(p, "rb").read()
        except OSError:
            skipped.append((rel, "read-failed"))
            continue
        text, enc = decode(raw)
        if text is None:
            skipped.append((rel, enc))
            continue
        enc_count[enc] = enc_count.get(enc, 0) + 1
        for i, line in enumerate(text.splitlines(), 1):
            for name, pat, why in RULES:
                for m in re.finditer(pat, line):
                    frag = m.group(0)
                    if name == "minimax-key" and not re.fullmatch(
                            r"sk-[A-Za-z0-9]{40,}", frag):
                        continue
                    hits.append((rel, i, name, why, frag[:60]))

    mode = "已跟踪文件" if args.staged else "将要发布的内容（跟踪 + 未跟踪未忽略）"
    encs = "，".join(f"{k} {v}" for k, v in sorted(enc_count.items()))
    print(f"扫描 {len(files)} 个文件（{mode}，编码分布：{encs}）")
    if missing:
        print(f"⚠️  {len(missing)} 个路径在磁盘上找不到（已跳过，需检查）：")
        for m in missing[:10]:
            print("      ", m)
    if skipped:
        print(f"⚠️  {len(skipped)} 个文件未能解码（已跳过，可能藏内容）：")
        for rel, why in skipped[:10]:
            print(f"       {rel}  [{why}]")

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
