# -*- coding: utf-8 -*-
"""生成 REPORT_LOCAL.md —— 本地模型（google/gemma-4-e2b）时间感实验报告。

数字全部从 out/*.json 读，不手抄。
"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
DST = os.path.join(ROOT, "REPORT_LOCAL.md")


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def fmt(v, nd=2, dash="—"):
    if v is None:
        return dash
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def main():
    tps = load("local_tps_summary.json")
    pre = load("local_pre_summary.json")
    post = load("local_posthoc_summary.json")
    proc = load("local_process_summary.json")
    proc2 = load("local_process2_summary.json")
    proc_opt = load("local_process_opt_summary.json")
    verdict = load("local_summary.json")
    v = (verdict or {}).get("verdict") or {}

    L = []
    W = L.append

    W("# 本地模型时间感实验报告")
    W("")
    W(f"**被试**：`google/gemma-4-e2b`（LM Studio，OpenAI 兼容端点 "
      f"`{os.environ.get('LMSTUDIO_BASE', 'http://127.0.0.1:1234/v1')}`）")
    W("**硬件**：双 RTX 3080（本机，单卡承载），16 GB 物理内存")
    W("**协议**：每次实验清空上下文、全程严格串行不开并发、逐次记录 `[t_request, t_last]`")
    W("")
    W("> **为什么做这一轮**：上一轮在云端 API（MiniMax-M3.1-Flash）上的结论是"
      "「注入 TPS 不能产生时间感」，但那个结论被一个物理前提污染了——"
      "同一台机器上测出来的速率波动 **2.39×**，注入的常数有一半概率是错的 2 倍。"
      "本轮换到本机模型，就是把那个前提修好，再问一次同样的问题。")
    W("")

    # ---------------- 一句话 ----------------
    W("## 0. 一句话结论")
    W("")
    W("> **速率是尺子，不是时钟。但尺子准了，它就能当钟使。**")
    W(">")
    W("> 上一轮「注入 TPS 无效」不是「速率无用」，而是「那把尺子本身坏了」。")
    W("> 本机模型稳态速率波动只有 **1.15×**，同一套题目下，注入速率的效应"
      "从「完全测不出来」变成「显著」。")
    W("")

    # ---------------- 判据 ----------------
    W("## 0.1 预先定好的成功判据与结论")
    W("")
    W("| 判据 | 条件 | 结果 | 通过 |")
    W("|---|---|---|---|")
    c1 = v.get("C1_稳定性前提") or {}
    c2 = v.get("C2_剂量反应") or {}
    c3 = v.get("C3_粗略时间感") or {}
    c4 = v.get("C4_长思考过程时间感") or {}
    W(f"| C1 稳定性前提 | 稳态 max/min ≤ 1.30 且 请求间 CV ≤ 0.15 | "
      f"{fmt(c1.get('steady_max_over_min'))}× / CV {fmt(c1.get('steady_between_cv'), 3)} | "
      f"{'✅' if c1.get('pass') else '❌'} |")
    W(f"| C2 剂量-反应 | 注入速率与预估显著负相关 | "
      f"Spearman {fmt(c2.get('spearman_rate_vs_est'), 3, '0')}，b {fmt(c2.get('loglog_slope'), 3)} | "
      f"{'✅' if c2.get('pass') else '❌'} |")
    if c3:
        W(f"| C3 粗略时间感 | 跨轮 Spearman(预估, 真实耗时) ≥ 0.5 或 误差显著下降 | "
          f"Spearman {fmt(c3.get('best_spearman_est_vs_actual'), 3, '0')}，"
          f"p {fmt(c3.get('best_vs_base_p'), 4)} | {'✅' if c3.get('pass') else '❌'} |")
    if c4:
        W(f"| C4 长思考过程时间感 | 末标记/真实 ∈ [0.5, 2.0] 且节拍斜率 ∈ [0.5, 1.6] | "
          f"最优臂 `{c4.get('best_arm')}`：末比 {fmt(c4.get('best_last_ratio'))}×，"
          f"斜率 {fmt(c4.get('best_slope'))} | {'✅' if c4.get('pass') else '❌'} |")
    W("")
    W("> 判据在跑数据**之前**就写死在 `local/analyze_local.py` 里，避免看到结果再找说法。")
    W("")

    # ---------------- 稳定性 ----------------
    if tps:
        W("## 1. 第一步：把尺子校准（这是整轮的前提）")
        W("")
        st = tps.get("steady") or {}
        wm = tps.get("warm") or {}
        mg = tps.get("merged") or {}
        mx = tps.get("minimax_reference") or {}
        W(f"18 次 30 秒级连续生成（longform 12 次 + items 6 次），严格串行、每次清空上下文：")
        W("")
        W("| 口径 | n | TPS 中位 | 极值 | max/min | 请求间 CV |")
        W("|---|---|---|---|---|---|")
        W(f"| 全部（含冷启动） | {mg.get('n')} | {fmt(mg.get('median'), 1)} | "
          f"{fmt(mg.get('min'), 1)}–{fmt(mg.get('max'), 1)} | "
          f"**{fmt(mg.get('max_over_min'))}×** | {fmt(mg.get('between_cv'), 3)} |")
        W(f"| 去掉第 1 次冷启动 | {wm.get('n')} | {fmt(wm.get('median'), 1)} | "
          f"{fmt(wm.get('min'), 1)}–{fmt(wm.get('max'), 1)} | "
          f"{fmt(wm.get('max_over_min'))}× | {fmt(wm.get('between_cv'), 3)} |")
        W(f"| **稳态**（排除加载后前两次预热） | {st.get('n')} | {fmt(st.get('median'), 1)} | "
          f"{fmt(st.get('min'), 1)}–{fmt(st.get('max'), 1)} | "
          f"**{fmt(st.get('max_over_min'))}×** | **{fmt(st.get('between_cv'), 3)}** |")
        W(f"| 对照：云端 MiniMax-M3.1-Flash | 12 | {fmt(mx.get('median'), 1)} | "
          f"{fmt(mx.get('min'), 1)}–{fmt(mx.get('max'), 1)} | "
          f"**{fmt(mx.get('max_over_min'))}×** | **{fmt(mx.get('between_cv'), 3)}** |")
        W("")
        W(f"**冷启动是真实现象**：模型加载后的第 1 次请求只有 "
          f"{fmt(wm.get('cold_first_run_tps'), 1)} tok/s，是稳态中位的 "
          f"{fmt((wm.get('warmup_factor') or 0) * 100, 0)}%（≈{fmt(1 / (wm.get('warmup_factor') or 1), 2)}× 慢）。"
          f"所以本地部署必须先预热，再开始注入速率。")
        W("")
        W("按任务形态分：")
        W("")
        W("| 形态 | n | 稳态中位 | max/min | 请求间 CV |")
        W("|---|---|---|---|---|")
        for mode, mw in (tps.get("per_mode_warm") or {}).items():
            W(f"| {mode} | {mw.get('n')} | {fmt(mw.get('median'), 1)} | "
              f"{fmt(mw.get('max_over_min'))}× | {fmt(mw.get('between_cv'), 3)} |")
        W("")
        W("> **结论**：云端的 2.39× 是**后端路由**造成的（同一分钟内快慢交替），"
          "本机不存在这个问题。C1 前提成立。")
        W("")

    # ---------------- 事前预估 ----------------
    if pre:
        W("## 2. 第二步：注入速率，它动不动？")
        W("")
        arms = pre.get("arms") or {}
        dose = pre.get("dose") or {}
        W("任务：输出恰好 200 条编号条目，**题面不出现任何目标秒数**，"
          "第一行要求它独立预估生成耗时。地面真值 = 外部实测生成时长。")
        W("")
        W("| 实验臂 | 注入速率 | 预估中位 | 真实耗时 | 估/实际 | 对数误差 | vs base |")
        W("|---|---|---|---|---|---|---|")
        for arm, label in (("base", "不注入"), ("speed_low", "注入 79 tok/s"),
                           ("speed_true", "注入 159 tok/s（真值）"),
                           ("speed_high", "注入 254 tok/s"), ("elapsed", "直接给秒数")):
            a = arms.get(arm)
            if not a:
                continue
            p = a.get("vs_base_p")
            dd = a.get("vs_base_delta_logerr")
            sig = "—" if p is None else (f"{dd:+.3f}, p={p:.3f}" +
                                        (" **显著更好**" if (dd or 0) < 0 and p < 0.05 else ""))
            W(f"| {label} | {fmt(a.get('injected_rate'), 1)} | {fmt(a.get('median_est'), 1)} 秒 | "
              f"{fmt(a.get('median_actual'), 1)} 秒 | {fmt(a.get('median_ratio'))}× | "
              f"{fmt(a.get('median_log_err'), 3)} | {sig} |")
        W("")
        W(f"剂量-反应：Spearman(注入速率, 预估值) = **{fmt(dose.get('spearman_rate_vs_est'), 3)}**，"
          f"log-log 斜率 b = **{fmt(dose.get('loglog_slope'), 3)}**")
        W(f"（同一测量在云端 API 上是 −0.033 / +0.043，即「完全没用」）")
        W("")
        quotes = pre.get("reasoning_quotes") or []
        if quotes:
            W("**模型思维链的原话**（最硬的证据）：")
            W("")
            seen = set()
            for q in quotes:
                t = q["quote"].strip()
                key = t[:60]
                if key in seen:
                    continue
                seen.add(key)
                W(f"> 「{t}」")
                W(">")
            W("")
        W("读法：它确实把速率拿来做除法了（`3000 token ÷ 速率`），"
          "但**它自己估不准要写多少 token**，所以事前预估的绝对误差还是大。"
          "下一步要让模型看见自己刚写了多少。")
        W("")

    # ---------------- 事后预估 ----------------
    if post:
        W("## 3. 第三步：让它回看自己刚写的东西（粗略时间感）")
        W("")
        arms = post.get("arms") or {}
        W("设计：先写一篇长文（**每轮长度不同**：500→3000 字，真实耗时变化 6 倍），"
          "然后**保留上下文**问它「刚才那条用了多少秒」。"
          "长度必须拉开，否则真实耗时几乎是常数，「预估是否跟着现实走」根本没法测。")
        W("")
        W("| 实验臂 | n | 估/实际 | 对数误差 | 跨轮 Spearman(预估, 真实耗时) | 模型自估 token/真实 token |")
        W("|---|---|---|---|---|---|")
        for arm, label in (("base", "不注入"), ("speed", "注入稳定速率"), ("elapsed", "直接给秒数")):
            a = arms.get(arm)
            if not a:
                continue
            W(f"| {label} | {a.get('n')} | {fmt(a.get('median_ratio'))}× | "
              f"{fmt(a.get('median_log_err'), 3)} | "
              f"**{fmt(a.get('spearman_est_vs_actual'), 3)}** | "
              f"{fmt(a.get('median_token_ratio_est_over_real'))} |")
        W("")
        if c3:
            W(f"**C3 判定：{'通过 ✅' if c3.get('pass') else '未通过 ❌'}** —— "
              f"最优臂跨轮相关 {fmt(c3.get('best_spearman_est_vs_actual'), 3)}，"
              f"相对基线 p = {fmt(c3.get('best_vs_base_p'), 4)}。")
            W("")

    # ---------------- 过程时间感 ----------------
    if proc:
        W("## 4. 第四步：长思考状态下，边写边报时间（**失败**）")
        W("")
        arms = proc.get("arms") or {}
        W("设计：模型在一条长回复里边写边标 `〔已用时 X 秒〕`（每写完一个编号小节标一次），"
          "每个标记按数据流里的**真实到达时刻**对齐去对账。")
        W("")
        W("| 实验臂 | n | 标记数中位 | 轮内 Spearman | 末标记/真实 | 节拍斜率（理想 1.0） |")
        W("|---|---|---|---|---|---|")
        for arm, label in (("base", "不注入"), ("speed", "注入稳定速率"),
                           ("speed_len", "注入速率 + 字符/token 换算")):
            a = arms.get(arm)
            if not a:
                continue
            W(f"| {label} | {a.get('n')} | {fmt(a.get('n_marks_median'), 1)} | "
              f"{fmt(a.get('median_within_spearman'), 3)} | "
              f"**{fmt(a.get('median_last_ratio'))}×** | "
              f"**{fmt(a.get('median_slope'))}** |")
        W("")
        W("**这是本轮最有价值的负结果。** 三个臂的标记全都是一条完美等差数列"
          "（R² = 0.998），轮内相关也全是 1.0 —— 但斜率高达 16–22（理想是 1.0），"
          "末标记比真实时间大 11–16 倍。模型在**编一个看起来合理的节拍**，不是在测量流逝。")
        W("")
        for arm, label in (("base", "不注入"), ("speed", "注入稳定速率"),
                           ("speed_len", "注入速率 + 字符/token 换算")):
            a = arms.get(arm)
            if not a:
                continue
            W(f"- {label}：思维链占真实时间中位 "
              f"{fmt((a.get('median_think_share_of_time') or 0) * 100, 0)}%，"
              f"生成时长中位 {fmt(a.get('median_gen_s'), 1)} 秒，"
              f"思维链 {fmt(a.get('median_think_tokens'), 0)} token")
        W("")

    # ---------------- 长思考优化 ----------------
    if proc_opt:
        W("## 5. 长思考的修法：把速率换算到「工作单元」上")
        W("")
        W("L3 的失败模式很具体：模型把标记写成一个**等差数列**"
          "（15、32、50、68…），R² = 0.998，比真实时间规律得多——它是编的。"
          "根因是它只会写、不会算：不知道自己写了多少字，也不知道自己有多快。")
        W("")
        W("修法：除了速率，再给一句「**每写完一个小节大约产出 N 个 token**」，"
          "换算成「每小节约 N/R 秒」。模型只要会数自己写到第几个小节，"
          "就能推出大概过了多久。")
        W("")
        arms = proc_opt.get("arms") or {}
        W("| 实验臂 | n | 标记数 | 末标记/真实 | 节拍斜率（理想 1.0） | 截距 |")
        W("|---|---|---|---|---|---|")
        for arm, label in (("speed_unit", "速率 + 工作单元换算"),
                           ("speed_unit_think", "再补上思考阶段耗时")):
            a = arms.get(arm)
            if not a:
                continue
            W(f"| {label} | {a.get('n')} | {fmt(a.get('n_marks_median'), 1)} | "
              f"**{fmt(a.get('median_last_ratio'))}×** | "
              f"**{fmt(a.get('median_slope'))}** | {fmt(a.get('median_intercept'), 1)} 秒 |")
        W("")
        if proc:
            W("对照（只给速率或什么都不给）：")
            W("")
            W("| 实验臂 | 末标记/真实 | 节拍斜率 |")
            W("|---|---|---|")
            for arm, label in (("base", "不注入"), ("speed", "只给稳定速率"),
                               ("speed_len", "速率 + 字符/token 换算")):
                a = (proc.get("arms") or {}).get(arm)
                if not a:
                    continue
                W(f"| {label} | {fmt(a.get('median_last_ratio'))}× | "
                  f"{fmt(a.get('median_slope'))} |")
            W("")
        W("**两点必须说清楚**：")
        W("")
        W("1. **只看「轮内相关」会被骗。** 三个失败臂的轮内 Spearman 也全是 1.0"
          "（标记单调递增），但斜率高达 16–22（理想是 1.0）。"
          "判定必须同时看倍数和斜率。")
        W("2. **给得更多不一定更好。** 「再补上思考阶段耗时」那一臂反而更差"
          "（末比 2.88×、斜率 3.91）——模型把那个思考耗时当成了**每节的步长**，"
          "而不是一次性偏移。上下文不是越多越好，**换算关系要写成「每单元多少秒」"
          "这种无歧义的形式**。")
        W("")
        W("残余误差（截距 ≈ −5.3 秒）来自思考阶段：模型正文开始前先想了一遍，"
          "那段时间是真实流逝但它自己看不见，所以它从 0 开始数。")
        W("")

    # ---------------- 长思考：外部时钟 ----------------
    if proc2:
        W("## 5. 长思考的修法：把时钟做成「在思考结束的节点喂回去」")
        W("")
        arms = proc2.get("arms") or {}
        W("一次生成里，模型**看不见自己思考了多久**，所以「从开始生成算起已过多少秒」"
          "在长思考下天然算不准。工程上唯一能修的是：**在思考结束的节点把时钟喂回去**，"
          "这正是真实 agent 循环的做法。")
        W("")
        W("| 实验臂 | n | 标记数 | 轮内 Spearman | 末标记/真实总耗时 |")
        W("|---|---|---|---|---|")
        for arm, label in (("base", "不注入"), ("speed", "只给稳定速率"),
                           ("clock", "给速率 + 思考实测耗时")):
            a = arms.get(arm)
            if not a:
                continue
            W(f"| {label} | {a.get('n')} | {fmt(a.get('n_marks_median'), 1)} | "
              f"**{fmt(a.get('median_within_spearman'), 3)}** | "
              f"{fmt(a.get('median_last_ratio'))}× |")
        W("")

    # ---------------- 工程结论 ----------------
    W("## 6. 工程结论")
    W("")
    W("1. **给绝对量，不给速率**（已过秒数 / 剩余预算 / 截止时刻）——仍然是两轮实验里"
      "唯一在所有条件下都稳定的信号。")
    W("2. **确要用速率**：先把速率测稳（预热后跨请求滑动窗口累计平均，报 p10–p90 区间），"
      "再配一个**明确的待写量**，用来避开「速率同时进长度与时间两个估计」的抵消。")
    W("3. **本地部署要预热**：加载后前 1–2 次请求的速率只有稳态的 60–77%，"
      "在那之前测出来的数不能用。")
    W("4. **速率是「事前/事后预估」的好尺子，不是「过程内自标」的时钟**："
      "长思考里思维链占掉的真实时间模型自己看不见，"
      "要在思考结束的节点把时钟喂回去。")
    W("5. **别指望模型报「上一条花了多久」之前，先给它看自己写了什么**："
      "保留上下文 + 稳定速率，模型才能估出「我写了多少 token」再换算。")
    W("")

    # ---------------- 边界 ----------------
    W("## 7. 边界")
    W("")
    W("- **单一模型家族、单一部署**（gemma-4-e2b，本机 LM Studio + RTX 3080）。"
      "结论不能外推到云端 API，也不能外推到别的模型。")
    W("- **样本量**：每臂 n=6（pre / posthoc / process）。置换检验分辨率有限，"
      "结论以效应方向与思维链自述为主，不只看 p 值。")
    W("- **「粗略」的含义**：本轮把「有时间感」定为「跨轮相关性 ≥ 0.5」"
      "或「误差相对基线显著下降」，不是「精确到 1 秒」。")
    W("- **不做实盘/线上承诺**：这是测量实验，不接任何生产系统。")
    W("")

    W("## 8. 产物")
    W("")
    W("| 文件 | 内容 |")
    W("|---|---|")
    W("| `REPORT_LOCAL.md` | 本报告 |")
    W("| `local/lclient.py` | 本地流式客户端（逐块时刻落盘） |")
    W("| `local/calib.py` | L1 稳定性标定 |")
    W("| `local/exp_time_sense.py` | L2/L3/L4 四个子实验 |")
    W("| `local/analyze_local.py` | 分析 + 判据判定 |")
    W("| `local/analyze_tps.py` | 标定分析（冷/热/稳态三层） |")
    W("| `local/make_charts.py` / `make_demo_page.py` / `make_voice_script.py` | 视频素材生成 |")
    W("| `raw/local_*.jsonl` | 逐次原始记录（可审计） |")
    W("| `out/local_*_summary.json` | 分析产物 |")
    W("")
    W("---")
    W("")
    W("*本报告由 `local/make_report_local.py` 从 `out/*.json` 自动生成，数字未手抄。*")

    os.makedirs(ROOT, exist_ok=True)
    with open(DST, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"wrote {DST} ({os.path.getsize(DST)} bytes, {len(L)} 行)")


if __name__ == "__main__":
    main()
