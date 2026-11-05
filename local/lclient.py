# -*- coding: utf-8 -*-
"""本地 LM Studio 流式客户端（OpenAI 兼容）。

与 harness/client.py 保持同一套测量口径，便于和 MiniMax API 的数据直接对比：
  ttft_s      = t_first - t_request
  gen_s       = t_last  - t_first        （解码窗口）
  duration_s  = t_last  - t_request
  tps         = completion_tokens / gen_s  （含 reasoning token，和上一轮同口径）
  tps_content = content_tokens   / gen_s

本地模型的特殊处理：
  * 非流式请求在 LM Studio 这一版返回**空 body**（status 200），所以只用流式。
  * 可能有 reasoning_content（Gemma 4 是思考模型），单独收集，便于「长思考状态」分析。
  * 逐块到达时刻 + 每块字符数全量保留，用于滑动窗口速率分析。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

DEFAULT_BASE = os.environ.get("LMSTUDIO_BASE", "http://127.0.0.1:1234/v1")
DEFAULT_KEY = "lm-studio"
DEFAULT_MODEL = "google/gemma-4-e2b"


def clear_proxy_env() -> None:
    """清掉 MiniMax Code 注入的本地代理变量，避免 urllib 连到死端口。"""
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(k, None)


@dataclass
class TurnMetrics:
    arm: str = ""
    task_id: str = ""
    turn_index: int = -1
    t_request: float = 0.0
    t_first: float | None = None
    t_last: float = 0.0
    ttft_s: float | None = None
    gen_s: float = 0.0
    duration_s: float = 0.0
    prompt_tokens: int = 0
    out_tokens: int = 0
    think_tokens: int = 0
    content_tokens: int = 0
    total_tokens: int = 0
    chunk_count: int = 0
    tps: float = 0.0
    tps_out: float = 0.0
    content: str = ""
    reasoning: str = ""
    finish_reason: str = ""
    usage_present: bool = False
    error: str = ""
    chunk_times: list = field(default_factory=list)
    chunk_chars: list = field(default_factory=list)
    chunk_content_chars: list = field(default_factory=list)
    chunk_reason_chars: list = field(default_factory=list)
    gap_median: float | None = None
    gap_p95: float | None = None
    gap_max: float | None = None
    burst_frac: float | None = None
    # 思考态/正文态切换点（相对 t_request 的秒数）
    think_end_s: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class LocalClient:
    def __init__(self, base_url: str = DEFAULT_BASE, api_key: str = DEFAULT_KEY,
                 model: str = DEFAULT_MODEL, timeout: int = 900):
        clear_proxy_env()
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat(self, messages: list[dict], *, max_completion_tokens: int = 4000,
             temperature: float = 0.3, reasoning_effort: str | None = None,
             arm: str = "", task_id: str = "", turn_index: int = -1,
             capture_chunks: bool = True, extra_body: dict | None = None) -> TurnMetrics:
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_completion_tokens": max_completion_tokens,
            "temperature": temperature,
        }
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        if extra_body:
            body.update(extra_body)
        m = self._stream(body, arm, task_id, turn_index, capture_chunks)
        if m.error.startswith("HTTP 400") and reasoning_effort:
            body.pop("reasoning_effort", None)
            m2 = self._stream(body, arm, task_id, turn_index, capture_chunks)
            if not m2.error:
                m2.error = ""
                m = m2
        return m

    def _stream(self, body: dict, arm, task_id, turn_index, capture_chunks) -> TurnMetrics:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        m = TurnMetrics(arm=arm, task_id=task_id, turn_index=turn_index,
                        t_request=time.perf_counter())
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
                    ncc = nrc = 0
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
                    if capture_chunks:
                        chunk_times.append(now)
                        chunk_cc.append(ncc)
                        chunk_rc.append(nrc)
                        chunk_chars.append(ncc + nrc)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                detail = ""
            m.error = f"HTTP {e.code}: {detail}"
        except Exception as e:
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
            m.out_tokens = max(m.chunk_count, len(m.content))
            m.content_tokens = m.out_tokens

        if m.gen_s > 0:
            m.tps = m.out_tokens / m.gen_s
            m.tps_out = m.content_tokens / m.gen_s

        if capture_chunks and len(chunk_times) >= 2:
            # ★ 必须把逐块时刻落盘：过程时间感实验要靠它把「〔已用时 X 秒〕」
            #   标记定位到流里的真实经过秒数，漏了就没法做对照。
            m.chunk_times = [round(t - m.t_request, 6) for t in chunk_times]
            m.chunk_chars = list(chunk_chars)
            m.chunk_content_chars = list(chunk_cc)
            m.chunk_reason_chars = list(chunk_rc)
            gaps = [chunk_times[i] - chunk_times[i - 1] for i in range(1, len(chunk_times))]
            gs = sorted(gaps)
            m.gap_median = round(gs[len(gs) // 2], 6)
            m.gap_p95 = round(gs[min(int(0.95 * len(gs)), len(gs) - 1)], 6)
            m.gap_max = round(gs[-1], 6)
            # reasoning 结束、content 开始的时间点
            if m.reasoning:
                last_r = max((t for t, r in zip(chunk_times, chunk_rc) if r > 0), default=None)
                if last_r:
                    m.think_end_s = round(last_r - m.t_request, 4)
            if chunk_chars and chunk_times:
                total_c = sum(chunk_chars)
                if total_c > 0:
                    cut = chunk_times[0] + 0.9 * (chunk_times[-1] - chunk_times[0])
                    tail = sum(c for c, t in zip(chunk_chars, chunk_times) if t >= cut)
                    m.burst_frac = round(tail / total_c, 3)
        return m
