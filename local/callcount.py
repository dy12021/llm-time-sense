# -*- coding: utf-8 -*-
"""统计真实调用次数：raw/*.jsonl 的行数。全项目共用这一份实现，避免口径漂移。

本轮（本地 LM Studio） = raw/local_*.jsonl
上一轮（云端 API）     = records.jsonl + phase_b_30s.jsonl + phase_b2.jsonl
"""
from __future__ import annotations

import os

CLOUD_FILES = ("records.jsonl", "phase_b_30s.jsonl", "phase_b2.jsonl")


def _count_lines(path: str) -> int:
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def count_calls(root: str) -> dict:
    raw = os.path.join(root, "raw")
    local = cloud = 0
    if os.path.isdir(raw):
        for fn in sorted(os.listdir(raw)):
            if fn.startswith("local_") and fn.endswith(".jsonl"):
                local += _count_lines(os.path.join(raw, fn))
        for fn in CLOUD_FILES:
            cloud += _count_lines(os.path.join(raw, fn))
    return {"local": local, "cloud": cloud, "total": local + cloud}
