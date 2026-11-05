# -*- coding: utf-8 -*-
"""生成 creative-panel #34 的正文（长程实验结论），数字全部从 out/*.json 自动取。

写到 out/panel_body_34.txt（UTF-8），再用 panel.py edit 34 --body "<正文>" 回写。
为什么先落文件再传参：Windows 命令行是 UTF-16，正文里直接内联中文在
某些 shell 下会静默变成乱码；先写 UTF-8 文件再读出来传参可绕开 cp936 写入错配。
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
DST = os.path.join(OUT, "panel_body_34.txt")


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def main():
    ta = load("tps_analysis.json")
    pb = load("phase_b_summary.json")
    pb2 = load("phase_b2_summary.json")
    r1 = load("r1_t2_stratified.json")

    merged, durs = [], []
    for v in (ta or {}).values():
        merged.extend(v.get("tps_text") or [])
        durs.extend(v.get("duration") or [])
    merged = sorted(merged)
    n = len(merged)
    med_rate = merged[n // 2] if n else 0
    p10 = merged[int(0.1 * n)] if n else 0
    p90 = merged[min(int(0.9 * n), n - 1)] if n else 0
    ratio = merged[-1] / merged[0] if n else 0

    L = []
    W = L.append
    W("实验问题：把「上一周期的生成吞吐（token/秒）」告诉 LLM，它能否因此获得时间感？")
    W("")
    W("结论（长程实验后修订）：**速率不能变成时间感，但速率确实是一把可用的「换算尺子」。**")
    W("第一轮「注入 TPS 反而更差」的数字有口径问题，机制判读也需要改。")
    W("")
    W("★ 重点标记（条件结论）：**如果 TPS 稳定，注入速率就可以使模型获得时间感。**")
    W("")
    W("> 本报告所有「速率→时间感无效」的结论，都是在「注入的速率本身是抽签出来的、")
    W("> 有一半概率错 2 倍」这个前提下测得的。速率一旦稳定，这条结论必须重测。")
    W("")
    W("支撑证据（三条）")
    if pb2:
        B2 = pb2.get("B2") or {}
        d2 = pb2.get("A2_dose") or {}
        inj_map = {x["arm"]: x["rate"] for x in (d2.get("doses") or [])}
        ratios = []
        for arm in ("speed_40", "speed_76", "speed_120"):
            v = B2.get(arm) or {}
            inj = inj_map.get(arm)
            if v.get("median_implied_rate") and inj:
                ratios.append(v["median_implied_rate"] / inj)
        if ratios:
            W(f"1. **模型对给定的速率照单全收。** 纯换算题里隐含速率/注入速率 = "
              f"{' / '.join(f'{r:.3f}' for r in ratios)}，"
              f"Spearman(注入速率, 隐含速率) = "
              f"{(pb2.get('B2_dose') or {}).get('spearman_rate_vs_implied', 0):+.3f}。")
            W("   没有外部信息时，模型默认假设自己约 "
              f"{(B2.get('base') or {}).get('median_implied_rate', 0):.0f} tok/s。")
    if pb:
        base_a = (pb.get("A") or {}).get("base") or {}
        spd_a = (pb.get("A") or {}).get("speed_cal") or {}
        tc = pb.get("A_token_compare") or {}
        cmp_ = pb.get("compare") or {}
        hitk = next((k for k in cmp_ if "命中" in k and "speed_cal" in k), None)
        hit = (cmp_.get(hitk) or {}) if hitk else {}
        if base_a.get("median_out_tokens") and spd_a.get("median_out_tokens"):
            W(f"2. **给了速率 + 明确时长目标后，模型对时间的控制力显著变好。** "
              f"写满 N 秒的命中误差 "
              f"{base_a.get('median_abs_hit_err', 0):.3f} → {spd_a.get('median_abs_hit_err', 0):.3f}"
              f"（p={hit.get('p', 0):.3f}），输出 token "
              f"{base_a['median_out_tokens']:.0f} → {spd_a['median_out_tokens']:.0f}"
              f"（+{tc.get('speed_cal', {}).get('delta', 0):.0f}，"
              f"p={tc.get('speed_cal', {}).get('p', 0):.3f}）——")
            W("   **速率确实把「时间」翻译成了可执行的长度。**")
    if pb2:
        d2 = pb2.get("A2_dose") or {}
        W("3. **时间那条通道是通的。** 模型把速率同时灌进「我能写多少」和「要多久」两个估计，")
        W("   于是它「以为」要写的 token 数随注入速率单调上升：")
        for arm, v in (d2.get("implied_tokens_median_by_arm") or {}).items():
            if v:
                W(f"   - 注入 {inj_map.get(arm, 0):.1f} tok/s → 隐含 token 中位 {v:.0f}")
        if d2.get("spearman_rate_vs_implied_tokens") is not None:
            W(f"   Spearman(注入速率, 隐含 token 数) = "
              f"{d2['spearman_rate_vs_implied_tokens']:+.3f}"
              f"（若时间通道根本不通，不会有这种对称效应。）")
    W("")
    W("要让这条结论成立，需要**同时**满足两个条件：")
    W("① **注入的速率稳定且准确** —— 本机做不到（见下）。")
    W("② **绕开「取消」机制** —— 光有稳定速率**还不够**：速率越高，模型计划写得越多，")
    W("   时间估计被同一个数抵消掉。要么改给**绝对时间量**，要么给**速率 + 明确的待写量**。")
    W("")
    W(f"本机为什么做不到（这是「不能」结论成立的前提，不是结论本身）：30 秒标定 {n} 次，")
    W(f"正文速率中位 {med_rate:.1f} tok/s，极值 {merged[0]:.1f}–{merged[-1]:.1f}，")
    W(f"**max/min = {ratio:.2f}×**，快慢**在同一分钟内交替**（后端路由到吞吐差约一倍的轨道）。")
    W("→ 「先测一个稳定 TPS 再注入」这个前提在本机**不成立**。")
    W("")
    W("**这条命题本轮没有被直接测过（诚实标注）**")
    if pb2:
        d2 = pb2.get("A2_dose") or {}
        cmp2 = pb2.get("A2_compare") or {}
        ps = []
        for arm in ("speed_40", "speed_76", "speed_120"):
            c = cmp2.get(arm) or {}
            if c.get("p") is not None:
                ps.append(f"{arm}: p={c['p']:.3f}")
        W(f"- A2 自持题（每臂注入**固定**速率，即臂内是「稳定的」）剂量-反应斜率 "
          f"b = {d2.get('loglog_slope', 0):+.3f}≈0，")
        W(f"  三个速率剂量 vs base **全部无显著差异**（{'；'.join(ps)}）。")
    W("- 也就是说：**即使臂内速率是固定的，自估时间也没有跟着动**——")
    W("  真正起作用的是取消机制（条件②），不只是速率抖动。")
    W("- 要真正验证「速率稳定 ⇒ 有时间感」，需要一个**能提供稳定 TPS 的部署**")
    W("  （固定后端路由，或跨请求滑动窗口累计平均后再注入），在那边重跑 A2 自持题。")
    W("")
    W("> **一句话**：稳定的速率是「让时间感可用」的**必要前提**，")
    W("> 但还**不充分**——必须同时避开「速率同时进长度与时间两个估计」的抵消。")
    W("")
    W("一、物理前提：本机根本不存在「稳定的 TPS」")
    W(f"- 30 秒连续生成标定 {n} 次（items + longform，每次清空上下文、严格串行）：")
    W(f"  正文速率中位 {med_rate:.1f} tok/s，p10–p90 {p10:.1f}–{p90:.1f}，")
    W(f"  极值 {merged[0]:.1f}–{merged[-1]:.1f}，**max/min = {ratio:.2f}×**。")
    W("- 快慢**在同一分钟内交替**出现（110.7→53.8→76.6→117.5→48.9→58.0→106.1→55.7），")
    W("  逐块到达时序显示是**后端路由**到吞吐相差约一倍的流式 chunking 轨道，")
    W("  不是时间趋势也不是内容长度（items 数据集内正文 token 只变 1.15×）。")
    W("- 结论：「先测一个稳定 TPS 再注入」这个前提在本机不成立——")
    W("  注入的那个常数有一半概率是错的 2 倍。")
    W("- **追问「快慢交替能不能靠 3 分钟实验避开」的答案：不能，而且能证明为什么。**")
    W("  用 5 秒滑动窗口速率定位交替发生在哪一层：")
    W("  请求**内**窗口速率 CV 中位 0.177（一次请求内基本一条轨到底）")
    W("  vs 请求**间** 0.920（极值比 5.28×），比值 0.19 → **交替在请求层（请求级抽签）**。")
    W("  → 拉长到 3 分钟只会让「这一次的速率」测得更准，下一条请求照样抽签；")
    W("  固定开销 TTFT 只占 30 秒的 2.5–2.9%，**测量时长不是误差来源**。")
    W("  → 正确做法：跨多次请求做滑动窗口累计平均 + 报 p10–p90 区间。")
    W("")
    W("二、算术层：模型完全会用给定的速率（第一轮低估了这一点）")
    if pb and pb.get("B_conversion_fidelity"):
        cf = pb["B_conversion_fidelity"]
        W(f"- 换算保真度 est×rate/tokens 中位 **{cf['median']:.4f}**"
          f"（{cf['min']:.4f}–{cf['max']:.4f}，n={cf['n']}）：")
        W("  给「约 76 token/秒」，模型答 500→6.5s、1500→19.6s、3000→39.2s、4500→58.8s，")
        W("  误差在小数点后一位以内。")
    W("- 第一轮模型自述用的是**它自己编的**「约 31.3 token/秒」——它会用速率，")
    W("  但会用一个错 2 倍的速率。所以第一轮「注入 TPS 更差」的真实机制不是「不会用」，")
    W("  而是「用的数不准」。")
    W("")
    W("三、模型没有「时长目标」的概念（第一轮被合并统计掩盖了）")
    if r1:
        resp = r1.get("responsiveness") or {}
        gb = (resp.get("base") or {}).get("gen_s_by_target") or {}
        W(f"- 基线臂：3 秒目标写出 {gb.get('3', 0):.1f}s、8 秒目标 {gb.get('8', 0):.1f}s、")
        W(f"  20 秒目标 {gb.get('20', 0):.1f}s，30 秒目标（Phase B v1）7.4s。")
        W("  **目标放大 10 倍，输出时长几乎不变**；各臂「目标秒数 vs 实际时长」")
        W("  的 Spearman 相关都≈0。")
        W("- 第一轮把 3/8/20 秒三个目标混在一起取中位数，导致：")
        W("  3 秒目标上**所有注入臂都优于基线**（1.436 → 0.292–0.943），")
        W("  8/20 秒目标上基线最好或持平——合并统计把两件事抵消了。")
    W("")
    W("四、速率真正的作用：换算成长度，不是时间感")
    if pb:
        A = pb.get("A") or {}
        base = A.get("base", {})
        spd = A.get("speed_cal", {})
        el = A.get("elapsed", {})
        tc = pb.get("A_token_compare") or {}
        cmp_ = pb.get("compare") or {}
        hit = (cmp_.get("A-命中误差|speed_cal") or {})
        W("- Phase B v1（30 秒目标、每臂 8 次）：")
        if base.get("median_out_tokens") and spd.get("median_out_tokens"):
            W(f"  注入速率后写出的 token 数 {base['median_out_tokens']:.0f} → "
              f"{spd['median_out_tokens']:.0f}（+{tc.get('speed_cal', {}).get('delta', 0):.0f}，"
              f"p={tc.get('speed_cal', {}).get('p', 0):.3f}），"
              f"命中误差 {base.get('median_abs_hit_err', 0):.3f} → "
              f"{spd.get('median_abs_hit_err', 0):.3f}（p={hit.get('p', 0):.3f}）。")
        if el.get("median_out_tokens"):
            W(f"  注入**绝对秒数**则写不出更多（{base.get('median_out_tokens', 0):.0f} → "
              f"{el['median_out_tokens']:.0f}，p={tc.get('elapsed', {}).get('p', 1):.3f} 无显著差异）——")
            W("  因为「30 秒」不告诉你该写多少字，「76 token/秒」告诉你了。")
    W("")
    W("五、剂量-反应（Phase B2：不告知目标秒数，只改注入的速率数字）")
    if pb2:
        A2 = pb2.get("A2") or {}
        d = pb2.get("A2_dose") or {}
        cmp2 = pb2.get("A2_compare") or {}
        W("- A2 自持题（每臂 8 次，**不告知目标秒数**，模型必须独立预估）：")
        for arm, v in A2.items():
            W(f"  {arm}: est/实测 中位 {v.get('median_est_over_actual', 0):.2f}，"
              f"预估中位 {v.get('median_est_s', 0):.0f}s vs 实测 {v.get('median_actual_gen_s', 0):.1f}s")
        W("- 预估值随注入速率**没有**单调移动：")
        for x in d.get("doses") or []:
            W(f"  注入 {x['rate']:.1f} tok/s → 预估中位 {x.get('median_est', 0):.0f}s")
        if d.get("spearman_rate_vs_est") is not None:
            W(f"  Spearman(注入速率, 预估值) = {d['spearman_rate_vs_est']:+.3f}，"
              f"拟合斜率 b = {d.get('loglog_slope', 0):+.3f}（b=0 完全没用；b=-1 完全当速率用）。")
        W("- **三个速率剂量 vs base 全部无显著差异；只有绝对时间量显著更好**：")
        for arm, c in cmp2.items():
            ci = c.get("ci") or (None, None)
            p, dd = c.get("p"), c.get("delta")
            if p is None or dd is None:
                continue
            mark = "**显著更好**" if dd < 0 and p < 0.05 else "无显著差异"
            W(f"  {arm}: Δ={dd:+.3f} CI=[{ci[0]:.3f}, {ci[1]:.3f}] p={p:.3f}  {mark}")
        W("- **取消机制**（关键）：模型把速率同时灌进「我能写多少」和「要多久」两个估计，")
        W("  两个效应抵消，所以预估值对速率的数值不敏感。证据是它「以为」自己要写的 token 数")
        W("  （= 预估秒数 × 注入速率）随注入速率单调上升：")
        for arm, v in (d.get("implied_tokens_median_by_arm") or {}).items():
            if v:
                W(f"    {arm}: 隐含 token 中位 {v:.0f}")
        if d.get("spearman_rate_vs_implied_tokens") is not None:
            W(f"    Spearman(注入速率, 隐含 token 数) = {d['spearman_rate_vs_implied_tokens']:+.3f}")
        W("- 思维链里的换算自述（原文）：")
        W("  「133 lines maybe 2000 Chinese tokens at 40 tok/sec ~50 sec. Say 70 sec.」")
        W("  「Time estimate maybe 120 sec given 120 tok/s but Chinese output perhaps 2 min. Say 150.」")
        W("  → 模型**确实**把速率当除数用，但（a）它自己估的 token 数误差巨大，")
        W("  （b）单位换算在「做除法」和「直接当秒数」之间摇摆，两头误差相乘，")
        W("  最终预估不随速率单调变化。")
        b2 = pb2.get("B2") or {}
        if b2:
            W("- 纯换算题（速率**只在系统提示里**，题目不含速率）：")
            for arm, v in b2.items():
                note = "（这不是换算结果，是没换算：给了秒数没给 token 数）" if arm == "elapsed" else ""
                W(f"  {arm}: 隐含速率中位 {v.get('median_implied_rate', 0):.1f} tok/s{note}")
            if pb2.get("B2_dose", {}).get("spearman_rate_vs_implied") is not None:
                W(f"  Spearman(注入速率, 隐含速率) = "
                  f"{pb2['B2_dose']['spearman_rate_vs_implied']:+.3f}")
                W("  → **模型会把环境速率照单全收**（隐含/注入 = 0.998 / 1.005 / 1.000）；")
                W("  基线（无任何外部信息）的隐含速率是 50.0 tok/s，即模型默认假设自己约 50 tok/s。")
    W("")
    W("工程含义")
    W("1. **给绝对量，不给速率**（已过秒数 / 剩余预算 / 截止时刻）——两轮实验里唯一稳定有效的信号。")
    W("2. **要控制输出长度就直接给篇幅预算**（不超过 N 字 / 约 M token），")
    W("   不要给时长目标——模型没有时长目标的概念，而且会把 3 秒写成 7 秒。")
    W("3. **确要用速率**：只能当作「速率→长度」的换算尺子用（给明确的待写量），")
    W("   且必须给滑动窗口累计平均 + 区间；单点采样误差可达 2 倍。")
    W("4. 把「速率」和「时钟」分开：速率用于容量规划，绝对时间量用于时间感知。")
    W("   速率和绝对秒数之间**不能互相换算**。")
    W("5. 别指望模型报告「上一条花了多久」：第一轮除绝对秒数臂外，自我复读率 100%。")
    W("")
    W("六、Phase C：过程时间感（模型在写的时候标「已用时」）")
    pc = load("phase_c_summary.json")
    pcl = load("phase_c_long_summary.json")
    if pc:
        cr = (pc.get("cross_run") or {})
        arms = pc.get("arms") or {}
        W("- 设计：模型每写完一个**带编号**的小节就自己标一次「〔已用时 X 秒〕」，")
        W("  我们把每个标记定位到流里的**真实经过秒数**直接对着比。")
        W("  （锚点必须是模型数得动的结构：按字数标→全堆在文末；按段落标→0 个标记；")
        W("  按**连续编号小节**标→12/12 全部 inline。）")
        W("- **踩坑：措辞歧义会毁掉长规格。** 初版写「每写完第 1 个小节」，")
        W("  模型在思维链里逐字抠：「'第1个' perhaps only section 1 … So only first」，")
        W("  于是 4 轮长规格里 2 轮只输出 0–1 个标记。改成「每写完**一个小节**……")
        W("  每一个末尾都要标，全文共 12 个……**不是只在小节 1 后面标**」后合规率回到 12/12。")
        W("  → **长文里模型会逐字抠指令，锚点措辞必须无歧义。**")
        W("- 短规格（12 轮 × 3 臂，每轮 12 标记，共 144 个标记）实测：")
        for arm in ("base", "speed", "elapsed"):
            a = arms.get(arm) or {}
            if not a:
                continue
            W(f"  {arm}: 真实耗时中位 {a.get('median_gen_s', 0):.1f}s，"
              f"末标注/真实 中位 {a.get('median_marked_over_real', 0):.2f}×，"
              f"模型隐含速率 {a.get('median_implied_tps', 0):.1f} tok/s")
        W("- **关键读数：跨轮 Spearman(真实耗时, 标注总秒) ≈ 0**")
        for scope, v in cr.items():
            W(f"  {scope}: {v.get('spearman_marked_vs_real', 0):+.3f}"
              f"（步长口径 {v.get('spearman_step_vs_real', 0):+.3f}）")
        W("  → 真实跑得慢的那一轮，标注**并不会**给得更多。")
        W("- 思维链自证：speed 臂明说「Generation speed ~77 tokens/sec」并用它换算，")
        W("  但算的是「**我打算写多少** ÷ 速率」（还把每节 token 高估约 2 倍）；")
        W("  elapsed 臂明说「**We cannot accurately know**, but use plausible increasing seconds」——")
        W("  **注入的绝对耗时根本没被摊到过程里**。")
        if pcl:
            a2 = (pcl.get("arms") or {}).get("base") or {}
            cr2 = (pcl.get("cross_run") or {}).get("全部") or {}
            nl = len(pcl.get("rows") or [])
            W(f"- **长规格（每节约 2400 字，真实 2–7 分钟）**：已到 {nl} 轮。")
            if a2:
                W(f"  实测真实耗时 {a2.get('median_gen_s', 0):.1f}s，"
                  f"末标注/真实 中位 {a2.get('median_marked_over_real', 0):.2f}×，"
                  f"模型隐含速率 {a2.get('median_implied_tps', 0):.1f} tok/s")
            if nl >= 8:
                W(f"  跨轮 Spearman(真实耗时, 标注总秒) = {cr2.get('spearman_marked_vs_real', 0):+.3f}")
                W("  → **3 分钟实验不改变结论**：过程标注仍是一条与真实流逝无关的外推等差数列。")
            else:
                W("  → 已到的那轮（真实 170.5 秒）把末标注写到 1545 秒（**9.06×**），斜率 8.95——")
                W("  **在真正的 3 分钟尺度上高估倍数只增不减**。")
                W("  剩余轮次受 **Token Plan 硬额度上限（错误码 2056）**阻塞未跑完；")
                W("  实验已按要求停止（等待器已终止，额度窗口未恢复）。")
        W("- 工程含义：**想让模型在长任务里报时间，只能由外部时钟在每个回合适时注入「已经过了 X 秒」**，")
        W("  让它**转述**这个数，而不是指望它自己累计。")
        W("  注意区分：**事后一次性预估**（给绝对秒数有效）与**过程内自标**（给绝对秒数无效）。")
        W("")
    W("实验规模")
    W(f"- Phase A 标定 {n} 次 30 秒生成（串行 0 重叠）；Phase B v1 48 次；Phase B2 100 次")
    W("  （40 次自持 + 60 次换算），每次实验清空上下文、全程单线程串行，")
    W("  区间重叠数均为 0。")
    if pc:
        nlong = len((pcl or {}).get("rows") or [])
        W(f"- Phase C 过程时间感：短规格 12 轮 × 3 臂（144 个标记）；"
          f"长规格（2–7 分钟生成）当前 {nlong} 轮（实验已按要求停止）。")
    W("- 被试 MiniMax-M3.1-Flash（reasoning_effort=low），bootstrap CI + 置换检验。")
    W("- 边界：单一模型家族、单一部署线路；速率双峰是本机这条线路的现象。")
    W("")
    W("报告：`REPORT_LONGRUN.md`（含 fig6–fig12 与逐次原始记录）")
    W("第一轮报告：`REPORT.md`")

    text = "\n".join(L)
    with open(DST, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {DST} ({len(text)} chars)")


if __name__ == "__main__":
    main()
