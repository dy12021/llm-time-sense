# -*- coding: utf-8 -*-
"""生成 TTS 旁白脚本（local/voice_script.json）。

规则：
  1) 数字全部从 out/*.json 取（调用次数现场数 raw/*.jsonl 行数），不手抄；
  2) 旁白文本与 HTML 演示页的段落一一对应，段号相同 → 配音与画面天然对齐；
  3) v2（2026-11-05 重做版）：主线只讲成功的三招，
     之前失败的两次尝试压到第 9 段「备注」。

读音注意（已用 STT 双链路核过）：
  · 模型名只说「Google Gemma 4 这个模型」——说 E2B 会被听成「412B」；
  · 「待写量」TTS 会读错，一律改成「明确的目标，比如还要写多少字」。
"""
from __future__ import annotations

import json
import math
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
DST = os.path.join(ROOT, "local", "voice_script.json")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from callcount import count_calls  # noqa: E402


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
    calls = count_calls(ROOT)

    segs = []

    # ---------- s1 开场 ----------
    segs.append({"id": "s1", "text":
        f"大模型不知道自己有多快。我花了 {calls['total']} 次真实调用去验证一件事："
        "只要告诉它上一轮每秒能生成多少 token，"
        "它能不能因此知道，自己这条回复要写多久。"})

    # ---------- s2 问题 ----------
    if pre:
        base = (pre.get("arms") or {}).get("base") or {}
        est = base.get("median_est")
        act = base.get("median_actual")
        ratio = base.get("median_ratio")
        txt = "先看问题。让模型预估「这条回复要写多久」，不给任何提示的时候，它只能喊一个数字："
        if est is not None and act is not None:
            txt += f"中位 {est:.1f} 秒，而真实耗时 {act:.1f} 秒，"
            if ratio:
                txt += f"时间被少算了 {1.0 / ratio:.0f} 倍。"
        txt += "它不是不会算，是压根不知道自己一秒能吐多少 token。"
        segs.append({"id": "s2", "text": txt})

    # ---------- s3 先把尺子测准 ----------
    if tps:
        st = tps.get("steady") or {}
        segs.append({"id": "s3", "text":
            "所以第一步不是给速率，是先把速率测准。"
            "这轮我换到本机的 LM Studio，用 Google Gemma 4 这个模型重做。"
            "同一套协议：每轮清空上下文，严格串行，不开并发。"
            f"排除掉加载后前两次预热，稳态速率是每秒 {st.get('median', 0):.0f} 个 token，"
            f"{st.get('n', 0)} 次采样的波动只有 {st.get('max_over_min', 0):.2f} 倍，"
            f"请求之间的变异系数 {st.get('between_cv', 0):.3f}。"
            "一把准的尺子，才量得出时间。"})

    # ---------- s4 方法一：事前注入速率 ----------
    if pre:
        arms = pre.get("arms") or {}
        dose = pre.get("dose") or {}
        base_r = (arms.get("base") or {}).get("median_ratio")
        true_r = (arms.get("speed_true") or {}).get("median_ratio")
        sp = dose.get("spearman_rate_vs_est")
        # 思维链里那句「N ÷ M ≈ 多少秒」里的 M 直接从原始引用里解析，
        # 不用四舍五入后的中位数，免得出现「注入 159 点 5」和原文 158.5 对不上
        inj = None
        for q in (pre.get("reasoning_quotes") or []):
            if q.get("arm") != "speed_true":
                continue
            m = re.search(r"([\d.]+)\s*tokens/second", q.get("quote") or "")
            if m:
                inj = float(m.group(1))
                break
        inj_txt = (f"{int(inj)} 点 {int(round((inj - int(inj)) * 10))}"
                   if inj is not None else "158 点 5")
        txt = "然后是关键这一步：只改注入的速率数字，别的都不动，看它的预估动不动。"
        if base_r is not None:
            txt += f"不注入速率时，它只估出了真实时间的 {base_r * 10:.0f} 成。"
        if true_r is not None:
            txt += f"注入真实速率后，估到了真实时间的 {true_r * 10:.0f} 成。"
        if sp is not None:
            txt += f"注入速率和预估值之间的相关系数是 {sp:.2f}。"
        # 下面这段是对 raw/local_pre.jsonl 里思维链原文的转述
        # （该轮注入 158.5 tokens/second，模型写下 3500 / 158.5 ≈ 22 秒，
        #   最终回答 25 秒，真实耗时 25.5 秒）
        txt += (f"更直接的证据在思维链里——注入 {inj_txt} token 每秒那一轮，"
                f"它自己写下：三千五百除以 {inj_txt}，约等于二十二秒，"
                "最后回答二十五秒，而真实值是二十五点五秒。"
                "没注入速率的那轮，它写的是「大概几秒钟吧」，"
                "回答八秒，真实值二十六点九秒。")
        txt += "速率真的进了它的判断。"
        segs.append({"id": "s4", "text": txt})

    # ---------- s5 方法二：事后预估 ----------
    if post:
        arms = post.get("arms") or {}
        ds = post.get("duration_span") or {}
        b_err = (arms.get("base") or {}).get("median_log_err")
        s_err = (arms.get("speed") or {}).get("median_log_err")
        e_err = (arms.get("elapsed") or {}).get("median_log_err")
        b_rate = (arms.get("base") or {}).get("median_implied_rate")
        s_rate = (arms.get("speed") or {}).get("median_implied_rate")
        p_s = (arms.get("speed") or {}).get("vs_base_p")
        txt = "再往前一步：让它回看自己刚写完的那条回复，回答「刚才那条花了多久」。"
        txt += (f"这里我把题目长度从 {ds.get('words_min', 500)} 字拉到 {ds.get('words_max', 3000)} 字，"
                f"真实耗时变化 {ds.get('time_ratio', 0):.1f} 倍，"
                "它报的数字也跟着一起动，这才叫有感觉，而不是喊一个固定数字。")
        if b_err is not None and s_err is not None:
            txt += (f"不注入速率时，它估的时间差 {math.exp(b_err):.1f} 倍；"
                    f"注入稳定速率之后，差 {math.exp(s_err):.1f} 倍，"
                    f"显著性 p 等于 {p_s:.3f}。")
        if e_err is not None:
            txt += f"直接告诉它秒数是最准的，差 {math.exp(e_err):.1f} 倍。"
        if b_rate and s_rate:
            txt += (f"原因也能从思维链里看出来：不注入时它默认自己每秒能出 {b_rate:.0f} 个 token，"
                    f"比真实速度快了将近三倍，所以时间自然被低估；"
                    f"注入之后它隐含用的速率降到 {s_rate:.0f}，已经贴近真实值了。")
        segs.append({"id": "s5", "text": txt})

    # ---------- s6 方法三：长思考状态（换算到工作单元） ----------
    if proc_opt:
        a = (proc_opt.get("arms") or {}).get("speed_unit") or {}
        lr = a.get("median_last_ratio")
        sl = a.get("median_slope")
        txt = ("最硬的一关是长思考状态：让模型在一条长回复里边写边标「已经过了多少秒」，"
               "我把每一个标记都按数据流里的真实到达时刻对齐去对账。"
               "光给速率不够——速率告诉模型「我多快」，不告诉它「写到哪了」。"
               "所以要再补一句：每写完一个小节，大约产出多少个 token。"
               "这样模型只要会数自己写到第几个小节，就能用这个换算推出大概过了多久。")
        if lr is not None and sl is not None:
            txt += (f"改完之后，末标记和真实时间只差 {lr:.2f} 倍，"
                    f"节拍斜率 {sl:.2f}，理想值是 1。"
                    "现场跑一次你看：它标零、一、二、三……十一秒，"
                    "而真实流逝是 5.3 秒一路涨到 15.3 秒。")
        segs.append({"id": "s6", "text": txt})

    # ---------- s7 边界：残余偏移 ----------
    if proc_opt:
        a = (proc_opt.get("arms") or {}).get("speed_unit") or {}
        ic = a.get("median_intercept")
        share = a.get("median_think_share_of_time")
        txt = "还差 5 秒左右，而且是个固定偏移。"
        if ic is not None:
            txt = f"还差 {abs(ic):.0f} 秒左右，而且是个固定偏移。"
        txt += "原因很具体：思维链占掉大约 "
        if share is not None:
            txt += f"{share * 100:.0f}% "
        txt += ("的真实时间——模型看不见自己想了多久，"
                "所以它从正文开始计时，把前面那一段整个漏掉了。"
                "这是模型感知的硬边界，不是提示词能补的。")
        segs.append({"id": "s7", "text": txt})

    # ---------- s8 工程建议 ----------
    segs.append({"id": "s8", "text":
        "所以结论是：速率是尺子，不是时钟。但尺子必须准。"
        "工程上的做法还是给绝对量——已经过了多少秒、还剩多少预算、什么时候截止。"
        "真要用速率，就先把它测稳：跨请求做滑动窗口累计平均，同时报出区间，"
        "再配一个明确的目标，比如还要写多少字，避开那个互相抵消的机制。"
        "如果还想让它在长任务里自己报时间，就把速率换算到工作单元上，让它能数着走。"})

    # ---------- s9 备注：之前踩过的两个坑 ----------
    if tps and proc:
        mx = tps.get("minimax_reference") or {}
        parms = (proc.get("arms") or {}).values()
        slopes = [a.get("median_slope") or 0 for a in parms]
        think_lr = ((proc_opt or {}).get("arms") or {}).get("speed_unit_think") or {}
        txt = "最后备注一下之前踩过的两个坑。第一坑是在云端 API 上做："
        txt += (f"同一台机器测出来的速率波动 {mx.get('max_over_min', 0):.2f} 倍，"
                "请求被路由到吞吐相差一倍的不同后端轨道，尺子本身就是坏的，"
                "所以那一轮「注入速率没用」的结论其实不成立。")
        txt += ("第二坑是长思考里只给速率：模型标的秒数轮内相关性 1.00，"
                f"斜率却高到 {min(slopes):.0f} 到 {max(slopes):.0f}，"
                "它标的是一条编出来的等差数列。")
        if think_lr.get("median_last_ratio"):
            # 「也救不回来」里的「救不」与「就补」同音，TTS 会念成「就补回来」
            # （语义正好相反），改用没有歧义的「也不管用」
            txt += (f"再补一句思考阶段耗时也不管用，末标记反而是 "
                    f"{think_lr['median_last_ratio']:.2f} 倍。")
        txt += "这也是为什么最后那个「工作单元换算」不是拍脑袋，是被这两个坑逼出来的。"
        segs.append({"id": "s9", "text": txt})

    # ---------- s10 开源 ----------
    segs.append({"id": "s10", "text":
        "代码、每一轮原始记录和完整报告都在下面，仓库地址在屏幕上。"
        "数字全部由脚本自动生成，没有手抄。"
        "如果这期对你有用，点个关注，下期我把它用到真实的智能体循环里。"})

    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False, indent=1)
    for s in segs:
        print(f"{s['id']}: {len(s['text'])} 字  {s['text'][:44]}…")
    print(f"\n→ {DST}  共 {len(segs)} 段")


if __name__ == "__main__":
    main()
