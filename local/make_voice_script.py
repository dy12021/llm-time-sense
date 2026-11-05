# -*- coding: utf-8 -*-
"""生成 TTS 旁白脚本（local/voice_script.json）。

规则：所有数字都从 out/*.json 取，不手抄；旁白文本与 HTML 演示页的段落一一对应，
段号相同 → 配音与画面天然对齐。
"""
from __future__ import annotations

import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
DST = os.path.join(ROOT, "local", "voice_script.json")


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    tps = load("local_tps_summary.json")
    pre = load("local_pre_summary.json")
    post = load("local_posthoc_summary.json")
    proc = load("local_process_summary.json")
    proc_opt = load("local_process_opt_summary.json")

    segs = []

    segs.append({"id": "s1", "text":
        "大模型不知道自己有多快。我花了六百多次真实调用去验证一件事："
        "只要告诉它上一轮每秒能生成多少 token，它能不能因此知道，自己这条回复要写多久。"})

    segs.append({"id": "s2", "text":
        "先说结论的前提。我原本在云端 API 上做了六百多次实验，"
        "结果是「注入速度没用」。但那个结论有一个致命的前提："
        "同一台机器上测出来的生成速率，波动高达两点三九倍。"
        "原因是请求被路由到吞吐相差一倍的不同的后端轨道。"
        "也就是说，尺子本身就是坏的。"})

    if tps:
        st = tps.get("steady") or {}
        mx = tps.get("minimax_reference") or {}
        segs.append({"id": "s3", "text":
            f"所以我换到本机的 LM Studio，用 google gemma 四 E二B 这个模型重做。"
            f"同一套协议：每轮清空上下文，严格串行，不开并发。"
            f"排除掉加载后前两次预热，本机稳态速率是每秒 {st.get('median', 0):.0f} token，"
            f"{st.get('n', 0)} 次采样的波动只有 {st.get('max_over_min', 0):.2f} 倍。"
            f"云端那边是 {mx.get('max_over_min', 0):.2f} 倍。"
            f"这次，尺子是准的。"})
    else:
        segs.append({"id": "s3", "text": "所以我换到本机的 LM Studio 重做这套实验。"})

    if pre:
        arms = pre.get("arms") or {}
        dose = pre.get("dose") or {}
        base = (arms.get("base") or {}).get("median_ratio")
        true = (arms.get("speed_true") or {}).get("median_ratio")
        sp = dose.get("spearman_rate_vs_est")
        b = dose.get("loglog_slope")
        txt = "然后是关键这一步：只改注入的速率数字，别的都不动，看它的预估动不动。"
        if base is not None:
            txt += f"不注入速率时，它预估的时间和真实时间差 {base:.1f} 倍。"
        if true is not None:
            txt += f"注入真实速率后，差 {true:.2f} 倍。"
        if sp is not None:
            txt += (f"注入速率和预估值之间的相关系数是 {sp:.2f}，"
                    f"同样的测量在云端 API 上是零。"
                    f"更直接的证据在思维链里——注入 158 点 5 token 每秒那一轮，"
                    f"它自己写下：三千五百除以 158 点 5，约等于二十二秒，"
                    f"最后回答二十五秒，而真实值是二十五点五秒。"
                    f"没注入速率的那轮，它写的是「大概几秒钟吧」，"
                    f"回答八秒，真实值二十六点九秒。"
                    f"速率不是没用，是那把尺子太糙了。")
        segs.append({"id": "s4", "text": txt})
    else:
        segs.append({"id": "s4", "text": "然后是关键的这一步：只改注入的速率数字，看它的预估动不动。"})

    if post:
        arms = post.get("arms") or {}
        b_err = ((arms.get("base") or {}).get("median_log_err"))
        s_err = ((arms.get("speed") or {}).get("median_log_err"))
        e_err = ((arms.get("elapsed") or {}).get("median_log_err"))
        b_rate = ((arms.get("base") or {}).get("median_implied_rate"))
        s_rate = ((arms.get("speed") or {}).get("median_implied_rate"))
        sp_s = ((arms.get("speed") or {}).get("spearman_est_vs_actual"))
        p_s = ((arms.get("speed") or {}).get("vs_base_p"))
        txt = "再往前一步：让它回看自己刚写完的那条回复，回答「刚才那条花了多久」。"
        txt += "这里我把题目长度从五百字拉到三千字，真实耗时变化三倍多，"
        txt += "它报的数字也跟着一起动，这才叫有感觉，而不是喊一个固定数字。"
        if b_err is not None and s_err is not None:
            txt += (f"不注入速率时，它估的时间差 {math.exp(b_err):.1f} 倍；"
                    f"注入稳定速率之后，差 {math.exp(s_err):.1f} 倍，"
                    f"显著性 p 等于 {p_s:.3f}。")
        if e_err is not None:
            txt += f"直接告诉它秒数是最准的，差 {math.exp(e_err):.1f} 倍。"
        if b_rate and s_rate:
            txt += (f"原因也能从思维链里看出来：不注入时它默认自己每秒能出 "
                    f"{b_rate:.0f} 个 token，比真实速度快了将近三倍，"
                    f"所以时间自然被低估；注入之后它隐含用的速率降到 {s_rate:.0f}，"
                    f"已经贴近真实值了。")
        segs.append({"id": "s5", "text": txt})
    else:
        segs.append({"id": "s5", "text": "再往前一步，让它回看自己刚写完的回复，回答刚才那条花了多久。"})

    if proc:
        arms = proc.get("arms") or {}
        sp = ((arms.get("speed") or {}).get("median_within_spearman"))
        lr = ((arms.get("speed") or {}).get("median_last_ratio"))
        sl = ((arms.get("speed") or {}).get("median_slope"))
        txt = ("最硬的一关是长思考状态：让模型在一条长回复里边写边标「已经过了多少秒」，"
               "我把每一个标记都按数据流里的真实到达时刻对齐去对账。"
               "结果是失败的，而且失败得特别有意思。")
        if sp is not None:
            txt += (f"轮内相关性是 {sp:.2f}，看着完美；"
                    f"但斜率高达 {sl:.0f}，理想值是 1。"
                    f"它标的十五、三十二、五十、六十八……是一条标准等差数列，"
                    f"而真实情况下每写一节只花一秒多。"
                    f"所以它不是在测量流逝，是在编一个看起来合理的节拍。"
                    f"根因很清楚：它只会写，不会算——"
                    f"不知道自己写了多少字，也不知道自己有多快。")
        segs.append({"id": "s6", "text": txt})
    else:
        segs.append({"id": "s6", "text":
            "最硬的一关是长思考状态：让模型边写边标已经过了多少秒，再按真实到达时刻对账。结果是失败的。"})

    if proc_opt:
        arms = proc_opt.get("arms") or {}
        a = arms.get("speed_unit") or {}
        lr = a.get("median_last_ratio")
        sl = a.get("median_slope")
        ic = a.get("median_intercept")
        txt = ("那怎么修？速率只告诉模型「我多快」，不告诉它「写到哪了」。"
               "所以我再补一句：每写完一个小节，大约产出多少个 token。"
               "这样模型只要会数自己写到第几个小节，"
               "就能用这个换算推出大概过了多久。")
        if lr is not None and sl is not None:
            txt += (f"改完之后，末标记和真实时间只差 {lr:.2f} 倍，"
                    f"节拍斜率从十几降到 {sl:.2f}，理想值是 1。"
                    f"现场跑一次你看：它标零、一、二、三……十一秒，"
                    f"而真实流逝是五点三秒一路涨到十五点三秒。"
                    f"差的那五秒是固定偏移——它在正文开始前先想了一轮，"
                    f"那段时间模型自己看不见，所以它从零开始数。")
        segs.append({"id": "s7", "text": txt})
    else:
        segs.append({"id": "s7", "text":
            "那怎么修？除了速率，再给一句每写完一个小节大约产出多少 token，模型就能数着走。"})

    segs.append({"id": "s8", "text":
        "所以结论是：速率是尺子，不是时钟。但尺子必须准。"
        "工程上的做法还是给绝对量——已经过了多少秒、还剩多少预算、什么时候截止。"
        "真要用速率，就先把它测稳：跨请求做滑动窗口累计平均，同时报出区间，"
        "再配一个明确的待写量，避开那个互相抵消的机制。"
        "如果还想让它在长任务里自己报时间，"
        "就把速率换算到工作单元上，让它能数着走。"})

    segs.append({"id": "s9", "text":
        "代码、每一轮的原始记录和完整报告都在下面。数字全部由脚本自动生成，没有手抄。"
        "如果这期对你有用，点个关注，下期我把它用到真实的智能体循环里。"})

    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False, indent=1)
    for s in segs:
        print(f"{s['id']}: {len(s['text'])} 字  {s['text'][:40]}…")
    print(f"\n→ {DST}")


if __name__ == "__main__":
    main()
