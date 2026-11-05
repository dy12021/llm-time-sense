# -*- coding: utf-8 -*-
"""Phase C —— **过程**时间感：模型在一条长回复的生成过程中，知不知道「已经过了多久」。

与前两轮的根本区别
------------------
第一轮/Phase B 测的都是**一次性预估**（回答前）或**事后自述**（写完再问）。
这一轮测的是**生成过程中**：模型每写一段就自己标一次时间，
我们把每个标记定位到流里的**真实经过秒数**，直接比较。

这个设计能区分四种机制
--------------------
1. **原始时间感**：模型内部有个钟。→ 标注 N_k 应与真实经过 t_k 成正比（斜率≈1），
   且**残差小**。
2. **按字数瞎猜**（无外部信息时的语感）：标注与累计字数成正比。
   在一次请求内速率较平稳时，这和「真实时间」几乎无法区分——
   所以关键读数是**绝对准确度**：语感推出来的秒数会和真实值系统性偏离。
3. **靠注入的速率推**：模型用「我写了 W 字 ÷ R tok/秒」算时间。
   → 标注会与**字数**严格成正比（斜率 = 目标总时长 / 总字数），
     而不是与真实经过时间成正比；一旦生成中速率变化就会露馅。
4. **靠注入的绝对量分配**：给了总时长，它把总时长按比例摊到各段。
   → 标注与真实时间的**斜率**接近 1，但**整体偏移**（总量摊错）。

三臂
----
base      无任何外部时间信息
speed     注入实测生成速率（Phase A 标定中位）——测「速率在过程感知里有没有用」
elapsed   注入**真实的**上一条同规格生成实测耗时——测「绝对量能不能被摊到过程里」

协议（沿用用户指定口径）
----------------------
- 每次实验 = 一次约 3 分钟的连续生成，**每次清空上下文**（只有一条用户消息）；
- **全程严格串行**，每次调用记录 [t_request, t_last]，分析脚本断言区间 0 重叠；
- 臂**逐轮交错**执行，消除顺序/漂移混淆。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics as st
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.client import LLMClient, load_llm_config  # noqa: E402
from harness import tasks as T  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")

ARM_ORDER = ["base", "speed", "elapsed"]

TOPICS = [
    "深海的热泉", "候鸟的迁徙", "森林的水循环", "古树的年轮",
    "潮汐与港口", "季风与农业", "候车的陌生人", "城市与海洋",
    "荒漠里的绿洲", "玻璃与光的语言",
]

# 标注标记：兼容中英文括号、冒号、空格
_MARK_RE = re.compile(
    r"[（(〔【]\s*已用时\s*[:：]?\s*(\d+(?:\.\d+)?)\s*秒\s*[)）〕】]")


def parse_marks(text: str) -> list[tuple[int, int, float]]:
    """返回 [(起始字符下标, 结束字符下标, 模型标注的秒数)]，按出现顺序。"""
    if not text:
        return []
    out = []
    for m in _MARK_RE.finditer(text):
        try:
            out.append((m.start(), m.end(), float(m.group(1))))
        except ValueError:
            pass
    return out


def char_time_map(rec) -> list[float]:
    """重建「每个正文字符的到达时刻（相对首 token）」。

    块内字符按均匀到达假设分配（块长 ~10-20 token、块间隔 0.07-0.16s，
    单点误差 ~0.1s，对 180 秒的尺度可忽略）。
    """
    m = rec["metrics"]
    gaps = m.get("chunk_gaps") or []
    cc = m.get("chunk_content_chars") or []
    if not gaps or len(cc) != len(gaps) + 1:
        return []
    times, t = [0.0], 0.0
    for g in gaps:
        t += g
        times.append(t)
    out = []
    for i, n in enumerate(cc):
        if n <= 0:
            continue
        dt = (times[i + 1] - times[i]) / n
        for k in range(n):
            out.append(times[i] + dt * (k + 1))
    return out


def build_system(arm: str, cal: dict, elapsed_hint: float | None) -> str:
    if arm == "base":
        return T.SYSTEM_BASE
    if arm == "speed":
        return (T.SYSTEM_BASE + "\n\n## 运行反馈（外部计时器实测）\n"
                f"- 实测生成速度：约 {cal['median']:.0f} token/秒。")
    if arm == "elapsed":
        if elapsed_hint is None:
            return T.SYSTEM_BASE
        return (T.SYSTEM_BASE + "\n\n## 运行反馈（外部计时器实测）\n"
                f"- 上一条同规格的长文，实测耗时 {elapsed_hint:.1f} 秒。")
    raise ValueError(arm)


PROMPT_C = """请写一篇长文，主题是「{topic}」。

硬性要求：
1. 至少写 {words} 字，内容要具体（可举例子、给数据、描述细节），
   不要提前收尾，也不要重复同一句话来凑字数。
2. **每写约 {seg} 字，在这一段的末尾另起一行加一个时间标记**，格式严格如下：
   〔已用时 X 秒〕
   其中 X 填一个整数，表示你估计「从开始生成到写完这一行」大约过了多少秒。
   这个标记要**出现在正文里**（不是只在最后写一次），大约每 {seg} 字出现一次，
   总共写 {nmarks} 个左右。
3. 只输出文章正文，不要标题、不要列表、不要说明。"""

PROMPT_C_PARA = """请写一篇长文，主题是「{topic}」。

硬性要求：
1. 至少写 {words} 字，内容要具体（可举例子、给数据、描述细节），
   不要提前收尾，也不要重复同一句话来凑字数。
2. 用自然段分段，每段 3–6 句。
3. **每写完 {para} 个自然段，就在那段末尾另起一行加一个时间标记**，格式严格如下：
   〔已用时 X 秒〕
   其中 X 填一个整数，表示你估计「从开始生成到写完这一行」大约过了多少秒。
   这个标记必须**紧跟在正文段落中间**，不能全部堆在文章最后——
   写完第一段就该有第一个标记，后面每 {para} 段再标一次。
4. 只输出文章正文，不要标题、不要列表、不要说明。

格式示例（只示范排版，内容与本题无关）：
　　热泉喷口的温度可以超过百度，水在高压下能在沸点以上保持液态……
　　这种被称作「超临界」的状态，是地球上少有的环境。
　　〔已用时 18 秒〕
　　1977 年，潜水器在加拉帕戈斯群岛附近第一次拍到这样的喷口……
"""

PROMPT_C_EVERY = """请写一篇长文，主题是「{topic}」。

硬性要求：
1. 至少写 {words} 字，内容要具体（可举例子、给数据、描述细节），
   不要提前收尾，也不要重复同一句话来凑字数。
2. 用自然段分段，每段 3–6 句。
3. **每写完 {para} 个自然段，就在那段末尾另起一行加一个时间标记**，格式严格如下：
   〔已用时 X 秒〕
   其中 X 填一个整数，表示你估计「从开始生成到写完这一行」大约过了多少秒。
   这个标记必须**紧跟在正文段落中间**，不能全部堆在文章最后。
4. 只输出文章正文，不要标题、不要列表、不要说明。"""


PROMPT_C_SECTIONS = """请写一篇长文，主题是「{topic}」。

硬性要求：
1. 全文分成 {nsect} 个**带连续编号**的小节，编号写成「1. 2. 3. …」这样的形式，每节约 {sect_chars} 字（不少于 {sect_lo} 字）。
2. **每写完一个小节，就在那节末尾另起一行加一个时间标记**——也就是说，
   {nsect} 个小节**每一个**的末尾都要有一个标记，全文共 {nsect} 个标记。
   格式严格如下：
   〔已用时 X 秒〕
   其中 X 填一个整数，表示你估计「从开始生成到写完这一行」大约过了多少秒。
   注意：不是只在小节 1 后面标，**每一节后面都要标**。
3. 内容要具体（可举例子、给数据、描述细节），不要提前收尾，也不要重复凑字数。
4. 只输出文章正文，从编号 1 开始，不要总标题、不要说明。"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default=",".join(ARM_ORDER))
    ap.add_argument("--trials", type=int, default=4, help="每臂重复次数")
    ap.add_argument("--words", type=int, default=9000, help="要求的最少字数")
    ap.add_argument("--seg", type=int, default=200, help="每隔多少字标一次时间")
    ap.add_argument("--target-s", type=float, default=180.0, help="目标生成秒数（仅自检）")
    ap.add_argument("--max-tokens", type=int, default=24000)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--out", default=os.path.join(RAW, "phase_c.jsonl"))
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--max-retries", type=int, default=6)
    ap.add_argument("--mark-mode", default="sections",
                    choices=["chars", "para", "sections"],
                    help="chars=每 N 字标一次；para=每 N 段标一次；"
                         "sections=每 N 个带编号小节标一次（模型能数编号，最可能 inline）")
    ap.add_argument("--para", type=int, default=1, help="每多少个自然段/小节标一次")
    ap.add_argument("--nsect", type=int, default=12, help="小节总数（mark-mode=sections）")
    ap.add_argument("--sect-chars", type=int, default=400,
                    help="每小节约多少字（mark-mode=sections）。要生成更长的文本就调大。")
    ap.add_argument("--spec", default=None,
                    help="规格标签，写进记录里区分不同批次（如 short / long3min）")
    ap.add_argument("--seed-elapsed", type=float, default=None,
                    help="elapsed 臂首轮的锚点（秒）。通常填一次校准试跑的实测生成时长。")
    args = ap.parse_args()

    calp = os.path.join(OUT, "tps_analysis.json")
    if not os.path.exists(calp):
        raise SystemExit(f"缺少标定结果 {calp}")
    d = json.load(open(calp, encoding="utf-8"))
    vals = []
    for v in d.values():
        vals.extend(v.get("tps_text") or [])
    vals = sorted(vals)
    cal = {"median": vals[len(vals) // 2],
           "p10": vals[int(0.1 * len(vals))],
           "p90": vals[min(int(0.9 * len(vals)), len(vals) - 1)]}
    print(f"注入用速率：标定中位 {cal['median']:.1f} tok/s（p10–p90 "
          f"{cal['p10']:.1f}–{cal['p90']:.1f}）", flush=True)

    done_keys = set()
    mode = "a"
    if args.fresh:
        mode = "w"
    elif os.path.exists(args.out):
        for line in open(args.out, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            # 失败过的记录不算「已完成」——续跑时要重试
            if r.get("metrics", {}).get("error"):
                continue
            done_keys.add((r["arm"], r["trial"]))
        print(f"续跑：已完成 {len(done_keys)} 条", flush=True)

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    # 每条记录的真实生成耗时（elapsed 臂的真实锚点）
    measured = {a: None for a in arms}
    seed = args.seed_elapsed  # 校准试跑给的真实实测值

    client = LLMClient(load_llm_config())
    out_f = open(args.out, mode, encoding="utf-8")
    err_f = open(os.path.join(RAW, "phase_c_errors.jsonl"), "a", encoding="utf-8")
    prev_t_last = None
    n_new = 0
    t0 = time.perf_counter()

    NET_ERR = ("ConnectionReset", "URLError", "Timeout", "timed out",
               "Connection aborted", "RemoteDisconnected", "BadStatusLine",
               "IncompleteRead", "Connection refused")

    def run(arm, trial, msgs):
        nonlocal prev_t_last
        m = None
        for attempt in range(1, args.max_retries + 1):
            if prev_t_last is not None:
                assert time.perf_counter() >= prev_t_last - 1e-6, "请求区间重叠！并发了"
            m = client.chat(msgs, max_completion_tokens=args.max_tokens,
                            temperature=args.temperature, reasoning_effort=args.effort,
                            arm=arm, task_id=f"C{trial}", turn_index=trial,
                            capture_chunks=True)
            prev_t_last = m.t_last
            if not m.error:
                return m
            if "429" in m.error or "2056" in m.error:
                # 2056 = Token Plan 硬额度上限，退避重试无效，要等额度窗口重置
                wait = 900 if "2056" in m.error else 90
                print(f"       额度受限（{m.error[:70]}），{wait}s 后重试 "
                      f"({attempt}/{args.max_retries})", flush=True)
            elif any(k in m.error for k in NET_ERR):
                wait = min(20 * attempt, 120)
                print(f"       网络错误（{m.error[:70]}），{wait}s 后重试 "
                      f"({attempt}/{args.max_retries})", flush=True)
            else:
                return m
            time.sleep(wait)
        return m

    try:
        for k in range(1, args.trials + 1):
            topic = TOPICS[(k - 1) % len(TOPICS)]
            for arm in rotate(arms, k - 1):
                if (arm, k) in done_keys:
                    continue
                hint = measured[arm] if measured[arm] is not None else seed
                sysmsg = build_system(arm, cal, hint)
                if args.mark_mode == "para":
                    prompt = PROMPT_C_PARA.format(topic=topic, words=args.words,
                                                  para=args.para)
                elif args.mark_mode == "sections":
                    sc = args.sect_chars
                    prompt = PROMPT_C_SECTIONS.format(topic=topic, nsect=args.nsect,
                                                      para=args.para, sect_chars=sc,
                                                      sect_lo=int(sc * 0.8))
                else:
                    nmarks = max(4, args.words // args.seg)
                    prompt = PROMPT_C.format(topic=topic, words=args.words,
                                             seg=args.seg, nmarks=nmarks)
                msgs = [{"role": "system", "content": sysmsg},
                        {"role": "user", "content": prompt}]
                m = run(arm, k, msgs)
                rec = {"phase": "C", "arm": arm, "trial": k, "topic": topic,
                       "spec": args.spec or f"{args.mark_mode}:{args.nsect}x{args.sect_chars}",
                       "words_req": args.words, "seg_chars": args.seg,
                       "mark_mode": args.mark_mode, "para": args.para,
                       "target_s": args.target_s,
                       "injected_rate": cal["median"] if arm == "speed" else None,
                       "injected_elapsed_s": hint,
                       "transport": client.transport,
                       "metrics": m.to_dict(), "ts": time.time()}
                if m.error:
                    # 失败记录单独放一个文件，不进主数据（主数据只留成功的）
                    err_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    err_f.flush()
                    print(f"  [C {arm:<9}] k{k} 失败（不计入）：{m.error[:70]}", flush=True)
                    continue
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_f.flush()
                n_new += 1
                measured[arm] = m.gen_s
                marks = parse_marks(m.content)
                print(f"  [C {arm:<9}] k{k} gen={m.gen_s:6.1f}s dur={m.duration_s:6.1f}s "
                      f"out_tok={m.out_tokens:6d} think={m.think_tokens:5d} "
                      f"cont={m.content_tokens:6d} tps={m.tps:6.1f} "
                      f"marks={len(marks):3d} finish={m.finish_reason}", flush=True)
    finally:
        out_f.close()
        err_f.close()

    dt = time.perf_counter() - t0
    print(f"\ndone: 新增 {n_new} 条，{dt/60:.1f} min（严格串行，每次清空上下文）")


def rotate(seq, k):
    if not seq:
        return list(seq)
    k %= len(seq)
    return list(seq[k:]) + list(seq[:k])


if __name__ == "__main__":
    main()
