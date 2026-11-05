# -*- coding: utf-8 -*-
"""Experiment runner.

Session layout
--------------
S1 (length calibration)  : for each task -> [estimate-then-answer] , [report previous]
S2 (fixed duration)      : for each target N -> [write to hit N s] , [token/strategy probe]
S3 (long horizon)        : 12 turns, alternating "elapsed since session start" /
                            "duration of previous reply", each with a small task

The arms differ ONLY in the feedback block of the system message.
Every completed cycle is measured (wall clock, tokens, tps) and written to JSONL
so the run is resumable and every number stays auditable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.client import LLMClient, TurnMetrics, load_llm_config  # noqa: E402
from harness import tasks as T  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "raw")


# --------------------------------------------------------------------------
# mock client — validates the whole pipeline without spending quota
# --------------------------------------------------------------------------


class MockClient:
    """Synthetic client: deterministic durations, plausible outputs."""

    def __init__(self, cfg=None):
        self.cfg = cfg or {"model": "MOCK"}

    def chat(self, messages, *, max_completion_tokens=1600, temperature=0.3,
             reasoning_effort="low", session_id="", arm="", turn_index=-1, task_id=""):
        import random
        rnd = random.Random(hash((session_id, turn_index, task_id)) & 0xFFFFFFFF)
        last_user = messages[-1]["content"]
        tps = 55.0 + rnd.uniform(-6, 6)
        think_ratio = 0.4

        # S2: scale the mock's output so that gen time lands near the target
        target_n = None
        if "大约为" in last_user and "秒" in last_user and "生成耗时" in last_user:
            import re as _re
            mm = _re.search(r"大约为\s*(\d+)\s*秒", last_user)
            if mm:
                target_n = int(mm.group(1))

        if target_n:
            content_tok = max(int(target_n * tps * rnd.uniform(0.7, 1.4)), 10)
        else:
            base = {"t1_1liner": 40, "t2_3sent": 90, "t3_list10": 220,
                    "t4_para": 300, "t5_code": 220, "t6_essay": 850}.get(task_id, 120)
            content_tok = max(int(base * rnd.uniform(0.85, 1.15)), 5)
        think_tok = int(content_tok * think_ratio)
        completion = content_tok + think_tok
        gen_s = completion / tps
        ttft = 1.2 + rnd.uniform(0, 0.8)

        m = TurnMetrics(session_id=session_id, arm=arm, turn_index=turn_index, task_id=task_id)
        m.t_request = 0.0
        m.t_first = ttft
        m.t_last = ttft + gen_s
        m.ttft_s = ttft
        m.gen_s = gen_s
        m.duration_s = ttft + gen_s
        m.prompt_tokens = 1000 + 50 * turn_index
        m.content_tokens = content_tok
        m.think_tokens = think_tok
        m.out_tokens = completion
        m.total_tokens = m.prompt_tokens + m.out_tokens
        m.chunk_count = max(completion // 8, 1)
        m.tps = m.out_tokens / m.gen_s
        m.tps_out = m.content_tokens / m.gen_s
        m.usage_present = True
        m.finish_reason = "stop"

        # plausible answers so the parsers have something to chew on
        if "预计耗时" in last_user:
            m.content = f"预计耗时：{max(int(gen_s * rnd.uniform(0.6, 1.8)), 1)}\n" + ("正文占位。" * 20)
        elif "回复耗时秒数" in last_user and "已过秒数" not in last_user:
            m.content = f"回复耗时秒数：{max(int(gen_s * rnd.uniform(0.5, 3.0)), 1)}"
        elif "已过秒数" in last_user:
            m.content = "占位正文。\n" + f"已过秒数：{max(int(gen_s * rnd.uniform(1.0, 6.0)), 1)}"
        elif "JSON" in last_user:
            m.content = json.dumps({"tokens": m.content_tokens, "strategy": "先估算篇幅再落笔"}, ensure_ascii=False)
        else:
            m.content = "占位正文。" * 30
        return m


# --------------------------------------------------------------------------
# session builders
# --------------------------------------------------------------------------


def build_s1(arm: str, repeat: int, client, records, out_f, max_tokens, effort, temperature):
    sid = f"S1-{arm}-r{repeat}"
    history = []
    cycle_log = []
    session_start = time.perf_counter()
    for i, (tid, task, _) in enumerate(T.S1_TASKS):
        # --- turn A: estimate own duration, then answer
        sys_msg = T.render_feedback(arm, cycle_log)
        prompt = T.S1_PROMPT_ESTIMATE.format(task=task)
        history.append({"role": "user", "content": prompt})
        messages = [{"role": "system", "content": sys_msg}] + history
        m = client.chat(messages, max_completion_tokens=max_tokens, temperature=temperature,
                        reasoning_effort=effort, session_id=sid, arm=arm, turn_index=len(cycle_log),
                        task_id=tid)
        est = T.parse_seconds(m.content, "预计耗时")
        _emit(records, out_f, dict(
            session_id=sid, session_type="S1", arm=arm, repeat=repeat, cycle=len(cycle_log) + 1,
            kind="S1_estimate", task_id=tid, question="pre_estimate", prompt=prompt,
            parsed={"estimate_s": est}, metrics=m.to_dict(),
            session_elapsed_at_prompt_s=None))
        history.append({"role": "assistant", "content": m.content})
        cycle_log.append(_cycle_entry(len(cycle_log) + 1, m, cycle_log))

        # --- turn B: report previous reply duration
        sys_msg = T.render_feedback(arm, cycle_log)
        prompt = T.S1_PROMPT_REPORT
        history.append({"role": "user", "content": prompt})
        messages = [{"role": "system", "content": sys_msg}] + history
        m2 = client.chat(messages, max_completion_tokens=max_tokens, temperature=temperature,
                         reasoning_effort=effort, session_id=sid, arm=arm, turn_index=len(cycle_log),
                         task_id=tid)
        rep = T.parse_seconds(m2.content, "回复耗时秒数")
        _emit(records, out_f, dict(
            session_id=sid, session_type="S1", arm=arm, repeat=repeat, cycle=len(cycle_log) + 1,
            kind="S1_report", task_id=tid, question="prev_duration", prompt=prompt,
            parsed={"estimate_s": rep}, metrics=m2.to_dict(),
            session_elapsed_at_prompt_s=time.perf_counter() - session_start))
        history.append({"role": "assistant", "content": m2.content})
        cycle_log.append(_cycle_entry(len(cycle_log) + 1, m2, cycle_log))
    return sid


def build_s2(arm: str, repeat: int, client, records, out_f, max_tokens, effort, temperature):
    sid = f"S2-{arm}-r{repeat}"
    history = []
    cycle_log = []
    session_start = time.perf_counter()
    for n in T.S2_TARGETS:
        sys_msg = T.render_feedback(arm, cycle_log)
        prompt = T.S2_PROMPT_WRITE.format(n=n, topic=T.S2_TOPICS[n])
        history.append({"role": "user", "content": prompt})
        messages = [{"role": "system", "content": sys_msg}] + history
        m = client.chat(messages, max_completion_tokens=max_tokens, temperature=temperature,
                        reasoning_effort=effort, session_id=sid, arm=arm, turn_index=len(cycle_log),
                        task_id=f"target{n}")
        _emit(records, out_f, dict(
            session_id=sid, session_type="S2", arm=arm, repeat=repeat, cycle=len(cycle_log) + 1,
            kind="S2_write", task_id=f"target{n}", question="fixed_duration", prompt=prompt,
            parsed={"target_s": n}, metrics=m.to_dict(),
            session_elapsed_at_prompt_s=None))
        history.append({"role": "assistant", "content": m.content})
        cycle_log.append(_cycle_entry(len(cycle_log) + 1, m, cycle_log))

        sys_msg = T.render_feedback(arm, cycle_log)
        prompt = T.S2_PROMPT_PROBE
        history.append({"role": "user", "content": prompt})
        messages = [{"role": "system", "content": sys_msg}] + history
        m2 = client.chat(messages, max_completion_tokens=max_tokens, temperature=temperature,
                         reasoning_effort=effort, session_id=sid, arm=arm, turn_index=len(cycle_log),
                         task_id=f"target{n}")
        obj = T.parse_json_obj(m2.content)
        _emit(records, out_f, dict(
            session_id=sid, session_type="S2", arm=arm, repeat=repeat, cycle=len(cycle_log) + 1,
            kind="S2_probe", task_id=f"target{n}", question="token_probe", prompt=prompt,
            parsed={"tokens": obj.get("tokens"), "strategy": obj.get("strategy")},
            metrics=m2.to_dict(),
            session_elapsed_at_prompt_s=time.perf_counter() - session_start))
        history.append({"role": "assistant", "content": m2.content})
        cycle_log.append(_cycle_entry(len(cycle_log) + 1, m2, cycle_log))
    return sid


def build_s3(arm: str, repeat: int, client, records, out_f, max_tokens, effort, temperature):
    sid = f"S3-{arm}-r{repeat}"
    history = []
    cycle_log = []
    session_start = time.perf_counter()
    for i, task in enumerate(T.S3_TASKS):
        is_elapsed = (i % 2 == 0)
        tmpl = T.S3_PROMPT_ELAPSED if is_elapsed else T.S3_PROMPT_PREV
        prompt = tmpl.format(task=task)
        sys_msg = T.render_feedback(arm, cycle_log)
        elapsed_at_prompt = time.perf_counter() - session_start
        history.append({"role": "user", "content": prompt})
        messages = [{"role": "system", "content": sys_msg}] + history
        m = client.chat(messages, max_completion_tokens=max_tokens, temperature=temperature,
                        reasoning_effort=effort, session_id=sid, arm=arm, turn_index=len(cycle_log),
                        task_id=f"s3_{i}")
        est = T.parse_seconds(m.content, "已过秒数" if is_elapsed else "回复耗时秒数")
        _emit(records, out_f, dict(
            session_id=sid, session_type="S3", arm=arm, repeat=repeat, cycle=len(cycle_log) + 1,
            kind="S3_task", task_id=f"s3_{i}",
            question="elapsed_since_start" if is_elapsed else "prev_duration",
            prompt=prompt, parsed={"estimate_s": est}, metrics=m.to_dict(),
            session_elapsed_at_prompt_s=elapsed_at_prompt))
        history.append({"role": "assistant", "content": m.content})
        cycle_log.append(_cycle_entry(len(cycle_log) + 1, m, cycle_log))
    return sid


def _cycle_entry(cycle: int, m, cycle_log: list | None = None) -> dict:
    prev_out = cycle_log[-1]["cum_out"] if cycle_log else 0
    prev_gen = cycle_log[-1]["cum_gen"] if cycle_log else 0.0
    cum_out = prev_out + m.out_tokens
    cum_gen = prev_gen + m.gen_s
    return {"cycle": cycle, "tps": m.tps, "duration_s": m.duration_s,
            "out_tokens": m.out_tokens, "content_tokens": m.content_tokens,
            "prompt_tokens": m.prompt_tokens,
            "cum_out": cum_out, "cum_gen": cum_gen,
            "cum_tps": (cum_out / cum_gen) if cum_gen > 0 else 0.0}


def _emit(records, out_f, rec):
    rec["ts"] = time.time()
    records.append(rec)
    out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    out_f.flush()
    m = rec["metrics"]
    extra = ""
    if rec["parsed"].get("estimate_s") is not None:
        extra = f" est={rec['parsed']['estimate_s']}s"
    print(f"  [{rec['arm']:<12}] {rec['session_type']} cyc{rec['cycle']:<3} {rec['kind']:<14}"
          f" dur={m['duration_s']:6.2f}s tps={m['tps']:6.1f} tok={m['total_tokens']:5d}{extra}"
          + (f"  ERR={m['error'][:80]}" if m["error"] else ""), flush=True)


# --------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default=",".join(T.ARMS))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--sessions", default="S1,S2,S3")
    ap.add_argument("--out", default=os.path.join(RAW_DIR, "records.jsonl"))
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--max-tokens", type=int, default=4000)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--fresh", action="store_true", help="ignore existing records")
    args = ap.parse_args()

    os.makedirs(RAW_DIR, exist_ok=True)
    done = set()
    if os.path.exists(args.out) and not args.fresh:
        with open(args.out, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["session_id"])
                except Exception:
                    pass
        print(f"resume: {len(done)} sessions already done")

    if args.mock:
        client = MockClient()
    else:
        client = LLMClient(load_llm_config())

    builders = {"S1": build_s1, "S2": build_s2, "S3": build_s3}
    records = []
    t0 = time.perf_counter()
    mode = "w" if args.fresh else "a"
    with open(args.out, mode, encoding="utf-8") as out_f:
        for rep in range(1, args.repeats + 1):
            arms = args.arms.split(",")
            # rotate arm order per repeat so a drifting server load cannot be
            # mistaken for an arm effect
            rot = (rep - 1) % len(arms)
            arms = arms[rot:] + arms[:rot]
            for arm in arms:
                for stype in args.sessions.split(","):
                    sid = f"{stype}-{arm}-r{rep}"
                    if sid in done:
                        print(f"skip {sid}")
                        continue
                    print(f"=== {sid} ===", flush=True)
                    try:
                        builders[stype](arm, rep, client, records, out_f,
                                        args.max_tokens, args.effort, args.temperature)
                    except Exception as e:
                        print(f"  !! session {sid} failed: {type(e).__name__}: {e}", flush=True)
    dt = time.perf_counter() - t0
    tot_tok = sum(r["metrics"].get("total_tokens", 0) for r in records)
    tot_out = sum(r["metrics"].get("out_tokens", 0) for r in records)
    n_err = sum(1 for r in records if r["metrics"].get("error"))
    print(f"done: {len(records)} turns in {dt/60:.1f} min -> {args.out}")
    print(f"      tokens: total={tot_tok} (content={tot_out}) | errors={n_err}"
          f" | avg {tot_tok/max(len(records),1):.0f} tok/turn")


if __name__ == "__main__":
    main()
