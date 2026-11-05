# -*- coding: utf-8 -*-
"""Streaming LLM client with precise per-chunk timing.

The whole experiment hinges on measuring the model's *own* throughput
(tokens/sec) and the wall-clock duration of each reply. Both come from the
SSE stream: we timestamp every chunk, then read the final usage object.

Measurement definitions (kept identical across every experimental arm):
  ttft_s      = t_first_token - t_request
  gen_s       = t_last_token - t_first_token          (decode window)
  duration_s  = t_last_token - t_request              (what a user waits)
  tps         = total_tokens / gen_s                  (headline throughput)
  tps_out     = out_tokens  / gen_s                   (visible-text throughput)
"""
from __future__ import annotations

import json
import os
import socket
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse


def prepare_transport(base_url: str) -> str:
    """决定这一次实验走「直连」还是「环境代理」。

    背景（2026-11-03 踩到）：MiniMax Code 会在环境里注入
    `HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:<port>`，那个本地代理进程挂掉后，
    urllib 会一直去连一个死端口，报 `WinError 10061 目标计算机积极拒绝`，
    看起来像「API 挂了」，其实是传输层的问题。

    做法：**先探直连**（TCP 到 API 主机:443，5 秒超时）。
    直连通 → 清掉代理环境变量，urllib 走直连；
    直连不通 → 保留代理环境变量，让 urllib 走原来的代理。

    返回 "direct" 或 "proxy"，调用方应当把它记进实验元数据，
    因为它会影响 TTFT 与观测到的吞吐分布。
    """
    saved = {k: os.environ.get(k) for k in
             ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
    host = urlparse(base_url).hostname or ""
    port = urlparse(base_url).port or (443 if base_url.startswith("https") else 80)
    ok = False
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.close()
        ok = True
    except Exception:
        ok = False
    if ok:
        for k in saved:
            os.environ.pop(k, None)
    return "direct" if ok else "proxy"


@dataclass
class TurnMetrics:
    session_id: str = ""
    arm: str = ""
    turn_index: int = -1
    task_id: str = ""
    t_request: float = 0.0
    t_first: float | None = None
    t_last: float = 0.0
    ttft_s: float | None = None
    gen_s: float = 0.0
    duration_s: float = 0.0
    prompt_tokens: int = 0
    out_tokens: int = 0          # completion_tokens: 模型本轮吐出的总 token(含思维链)
    think_tokens: int = 0        # 其中 reasoning_tokens
    content_tokens: int = 0      # 可见正文 token
    total_tokens: int = 0        # API 口径 prompt+completion
    chunk_count: int = 0
    tps: float = 0.0             # out_tokens / gen_s  <- 头号吞吐指标
    tps_out: float = 0.0         # content_tokens / gen_s
    content: str = ""
    reasoning: str = ""
    finish_reason: str = ""
    usage_present: bool = False
    error: str = ""
    # chunk-level timing (only filled when capture_chunks=True)
    chunk_gaps: list = field(default_factory=list)   # inter-arrival gaps (s)
    chunk_chars: list = field(default_factory=list)  # chars delivered per chunk
    chunk_content_chars: list = field(default_factory=list)
    chunk_reason_chars: list = field(default_factory=list)
    first_chunk_s: float | None = None               # t_first - t_request
    last_chunk_s: float | None = None                # t_last - t_request
    gap_median: float | None = None
    gap_p95: float | None = None
    gap_max: float | None = None
    burst_frac: float | None = None   # share of tokens arriving in the top 10% of time

    def to_dict(self) -> dict:
        return asdict(self)


def load_llm_config(path: str = "") -> dict:
    path = path or os.environ.get("MINIMAX_CONFIG", "")
    if not path or not os.path.exists(path):
        raise RuntimeError(
            "找不到 MiniMax 配置文件：请设置环境变量 MINIMAX_CONFIG 指向 config.toml"
            "（需要其中的 [llm] api_key）")
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    llm = cfg["llm"]
    return {
        "base_url": llm["base_url"].rstrip("/"),
        "api_key": llm["api_key"],
        "model": llm.get("model", "MiniMax-M3.1-Flash"),
    }


class LLMClient:
    """OpenAI-compatible streaming client. One instance = one experiment arm run."""

    def __init__(self, cfg: dict | None = None, timeout: int = 180):
        self.cfg = cfg or load_llm_config()
        self.timeout = timeout
        self.transport = prepare_transport(self.cfg["base_url"])

    def chat(
        self,
        messages: list[dict],
        *,
        max_completion_tokens: int = 1600,
        temperature: float = 0.3,
        reasoning_effort: str = "low",
        session_id: str = "",
        arm: str = "",
        turn_index: int = -1,
        task_id: str = "",
        capture_chunks: bool = False,
    ) -> TurnMetrics:
        body = {
            "model": self.cfg["model"],
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_completion_tokens": max_completion_tokens,
            "temperature": temperature,
            "reasoning_effort": reasoning_effort,
        }
        m = self._stream(body, session_id, arm, turn_index, task_id, capture_chunks)
        if m.error.startswith("HTTP 400"):
            # server may not accept stream_options -> retry without it
            body.pop("stream_options", None)
            m2 = self._stream(body, session_id, arm, turn_index, task_id, capture_chunks)
            if not m2.error:
                m2.error = ""
                m = m2
        return m

    def _stream(self, body: dict, session_id, arm, turn_index, task_id,
                capture_chunks=False) -> TurnMetrics:
        req = urllib.request.Request(
            f"{self.cfg['base_url']}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.cfg['api_key']}",
            },
            method="POST",
        )

        m = TurnMetrics(
            session_id=session_id,
            arm=arm,
            turn_index=turn_index,
            task_id=task_id,
            t_request=time.perf_counter(),
        )
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage = None
        chunk_times: list[float] = []
        chunk_chars: list[int] = []
        chunk_cc: list[int] = []
        chunk_rc: list[int] = []

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    now = time.perf_counter()
                    if m.t_first is None:
                        m.t_first = now
                    m.chunk_count += 1
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("usage"):
                        usage = obj["usage"]
                    nchar = 0
                    ncc = 0
                    nrc = 0
                    for ch in obj.get("choices") or []:
                        if ch.get("finish_reason"):
                            m.finish_reason = ch["finish_reason"]
                        delta = ch.get("delta") or {}
                        if delta.get("content"):
                            content_parts.append(delta["content"])
                            ncc += len(delta["content"])
                        if delta.get("reasoning_content"):
                            reasoning_parts.append(delta["reasoning_content"])
                            nrc += len(delta["reasoning_content"])
                    nchar = ncc + nrc
                    if capture_chunks:
                        chunk_times.append(now)
                        chunk_chars.append(nchar)
                        chunk_cc.append(ncc)
                        chunk_rc.append(nrc)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                detail = ""
            m.error = f"HTTP {e.code}: {detail}"
        except Exception as e:  # network hiccup, timeout, ...
            m.error = f"{type(e).__name__}: {e}"

        m.t_last = time.perf_counter()
        m.content = "".join(content_parts)
        m.reasoning = "".join(reasoning_parts)

        if m.t_first is not None:
            m.ttft_s = round(m.t_first - m.t_request, 4)
            m.gen_s = max(m.t_last - m.t_first, 1e-6)
        m.duration_s = max(m.t_last - m.t_request, 0.0)

        if usage:
            m.usage_present = True
            m.prompt_tokens = int(usage.get("prompt_tokens") or 0)
            m.out_tokens = int(usage.get("completion_tokens") or 0)
            det = usage.get("completion_tokens_details") or {}
            m.think_tokens = int(det.get("reasoning_tokens") or 0)
            m.content_tokens = max(m.out_tokens - m.think_tokens, 0)
            m.total_tokens = m.prompt_tokens + m.out_tokens
        else:
            # usage missing -> crude fallback (server batches ~8 tokens per chunk,
            # so chunk_count badly undercounts). Flagged via usage_present.
            m.prompt_tokens = 0
            m.out_tokens = max(m.chunk_count, len(m.content))
            m.think_tokens = 0
            m.content_tokens = m.out_tokens
            m.total_tokens = m.out_tokens

        if m.gen_s > 0:
            m.tps = m.out_tokens / m.gen_s
            m.tps_out = m.content_tokens / m.gen_s

        if capture_chunks and len(chunk_times) >= 2:
            gaps = [chunk_times[i] - chunk_times[i - 1] for i in range(1, len(chunk_times))]
            m.chunk_gaps = [round(g, 5) for g in gaps]
            m.chunk_chars = list(chunk_chars)
            m.chunk_content_chars = list(chunk_cc)
            m.chunk_reason_chars = list(chunk_rc)
            m.first_chunk_s = round(chunk_times[0] - m.t_request, 4)
            m.last_chunk_s = round(chunk_times[-1] - m.t_request, 4)
            gs = sorted(gaps)
            m.gap_median = round(gs[len(gs) // 2], 5)
            m.gap_p95 = round(gs[min(int(0.95 * len(gs)), len(gs) - 1)], 5)
            m.gap_max = round(gs[-1], 5)
            # how much of the token mass arrives in the last 10% of the stream
            # (a bursty server would push this towards 1.0)
            if chunk_chars and chunk_times:
                total_c = sum(chunk_chars)
                if total_c > 0:
                    cut = chunk_times[0] + 0.9 * (chunk_times[-1] - chunk_times[0])
                    tail = sum(c for c, t in zip(chunk_chars, chunk_times) if t >= cut)
                    m.burst_frac = round(tail / total_c, 3)
        return m
