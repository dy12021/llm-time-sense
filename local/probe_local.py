# -*- coding: utf-8 -*-
"""探针：本地 LM Studio (google/gemma-4-e2b) 的能力与吞吐基线。

要确认三件事：
  1. 接口是否接受 reasoning_effort（不接受会 400）；
  2. 「长思考」输出长什么样（reasoning_content / <think> 标签 / 都没有）；
  3. 真实吞吐（TTFT、tok/s、chunk 到达时序）。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.environ.get("LMSTUDIO_BASE", "http://127.0.0.1:1234/v1")
KEY = "lm-studio"
MODEL = "google/gemma-4-e2b"

# 清掉 MiniMax Code 注入的代理，避免走死端口
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)


def post(body: dict, timeout: int = 300):
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp, None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = ""
        return None, f"HTTP {e.code}: {detail}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def nonstream(prompt: str, extra: dict) -> tuple[dict | None, str]:
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": 400, "temperature": 0.3}
    body.update(extra)
    resp, err = post(body)
    if err:
        return None, err
    raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw), ""
    except json.JSONDecodeError:
        return None, f"NOT-JSON (status={resp.status}) raw[:400]={raw[:400]!r}"


def stream_timed(prompt: str, extra: dict, max_tokens: int = 1200):
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
            "stream": True, "stream_options": {"include_usage": True},
            "max_completion_tokens": max_tokens, "temperature": 0.3}
    body.update(extra)
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
        method="POST",
    )
    t0 = time.perf_counter()
    t_first = None
    chunks = 0
    content, reasoning = [], []
    usage = None
    finish = ""
    gaps = []
    last_t = None
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                now = time.perf_counter()
                if t_first is None:
                    t_first = now
                elif last_t is not None:
                    gaps.append(now - last_t)
                last_t = now
                chunks += 1
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                for ch in obj.get("choices") or []:
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
                    d = ch.get("delta") or {}
                    if d.get("content"):
                        content.append(d["content"])
                    if d.get("reasoning_content"):
                        reasoning.append(d["reasoning_content"])
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    t_end = time.perf_counter()
    ttft = (t_first - t0) if t_first else None
    gen = max((t_end - t_first), 1e-6) if t_first else 0.0
    out = "".join(content)
    rea = "".join(reasoning)
    res = {
        "chunks": chunks, "ttft_s": ttft, "gen_s": gen, "duration_s": t_end - t0,
        "finish": finish, "usage": usage,
        "content_len": len(out), "reasoning_len": len(rea),
        "content_head": out[:300], "reasoning_head": rea[:300],
        "has_think_tag": ("<think>" in out) or ("</think>" in out),
        "gap_median": (sorted(gaps)[len(gaps) // 2] if gaps else None),
        "gap_max": (max(gaps) if gaps else None),
    }
    if usage:
        ct = usage.get("completion_tokens") or 0
        res["out_tokens"] = ct
        res["tps"] = ct / gen if gen else 0
        det = usage.get("completion_tokens_details") or {}
        res["reasoning_tokens"] = det.get("reasoning_tokens")
        res["prompt_tokens"] = usage.get("prompt_tokens")
    return res


def main():
    print("=" * 70)
    print("1) 非流式 + reasoning_effort=low")
    r, err = nonstream("用一句话说明光合作用。", {"reasoning_effort": "low"})
    if err:
        print("  ERR", err)
    else:
        ch = (r.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        print("  finish:", ch.get("finish_reason"))
        print("  msg keys:", list(msg.keys()))
        print("  usage:", r.get("usage"))
        print("  content:", (msg.get("content") or "")[:160].replace("\n", " "))
        if msg.get("reasoning_content"):
            print("  reasoning_content:", msg["reasoning_content"][:200].replace("\n", " "))

    print("=" * 70)
    print("2) 非流式 + reasoning_format=unknown（探测 400 行为）")
    r, err = nonstream("用一句话说明光合作用。", {"reasoning_format": "unknown"})
    print("  ->", "OK" if not err else err[:200])

    print("=" * 70)
    print("3) 流式测速：普通短任务")
    res = stream_timed("用一句话说明光合作用。", {}, max_tokens=600)
    print("  ", json.dumps({k: v for k, v in res.items()
                            if k not in ("content_head", "reasoning_head")}, ensure_ascii=False))
    print("  content:", (res.get("content_head") or "")[:160].replace("\n", " "))

    print("=" * 70)
    print("4) 流式测速：诱导长思考（要求先推理再作答）")
    long_prompt = (
        "这是一道需要推理的问题：三个连续的开关，每个开关有两种状态，"
        "且每个开关的状态依赖前一个的奇偶性…（请认真推演）\n\n"
        "更实际一点：请思考「一个长度为 12 的二进制串，恰好有 7 个 1 的概率」"
        "的推导过程，写出完整推理步骤，然后给出结论。"
        "要求：先在推理过程里逐步推导，再给出最终答案。"
    )
    res2 = stream_timed(long_prompt, {}, max_tokens=2000)
    print("  ", json.dumps({k: v for k, v in res2.items()
                             if k not in ("content_head", "reasoning_head")}, ensure_ascii=False))
    print("  content:", (res2.get("content_head") or "")[:300].replace("\n", " "))
    if res2.get("reasoning_head"):
        print("  reasoning:", res2["reasoning_head"][:300].replace("\n", " "))


if __name__ == "__main__":
    main()
