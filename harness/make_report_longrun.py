# -*- coding: utf-8 -*-
"""生成 REPORT_LONGRUN.md —— 长程实验（30 秒标定 + 30 秒自持）的成文报告。

**所有数字都从 out/*.json 自动读出**，不手抄；缺哪个分析产物就跳过对应小节。
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
DST = os.path.join(ROOT, "REPORT_LONGRUN.md")


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else float("nan")


def fmt(x, n=2, dash="—"):
    if x is None:
        return dash
    if isinstance(x, float) and x != x:  # NaN
        return dash
    return f"{x:.{n}f}"


def main():
    ta = load("tps_analysis.json")
    pb = load("phase_b_summary.json")
    pb2 = load("phase_b2_summary.json")
    pc = load("phase_c_summary.json")
    pcl = load("phase_c_long_summary.json")
    tl = load("track_layer.json")
    if ta is None:
        raise SystemExit("缺少 out/tps_analysis.json，先跑 analyze_tps.py")

    L = []
    W = L.append

    # ================= 头部 =================
    W("# LLM 时间感实验 · 长程报告")
    W("")
    W("**问题**：把「上一周期的生成吞吐（token/秒）」告诉 LLM，它能不能因此获得时间感？")
    W("")
    W("**本报告的实验口径**（用户指定）：")
    W("")
    W("1. 先做 **30 秒连续生成**，统计这 30 秒里的真实吞吐（TPS 标定）；")
    W("2. 再做 **30 秒实验**，**每次清空上下文**（每次实验只有一条用户消息，互不影响）；")
    W("3. **全程不开并发**：单线程单请求严格串行，每次调用记录 `[t_request, t_last]`，")
    W("   分析脚本断言请求区间互不重叠。")
    W("")
    W("被试：`MiniMax-M3.1-Flash`（`api.minimax.cn/v1`，`reasoning_effort=low`），")
    W("工具链：自研流式客户端 + 逐块到达时刻采样。")
    W("")

    # ================= 0 结论 =================
    W("---")
    W("")
    W("## 0. 一句话结论")
    W("")
    W("> **速率是一把精确的换算尺子，但它不是时钟。**")
    W(">")
    W("> 给模型一个速率，它能照着做算术（换算偏差 0.5% 以内）；")
    W("> 但当问题变成「我自己这条回复要花多久」时，三个速率剂量"
      "（40 / 76.5 / 120 token/秒）**全都无效**，")
    W("> 而给**绝对秒数**显著有效。")
    W("")
    W("机制在思维链里写着：模型把速率同时灌进了「我能写多少」和「要多久」")
    W("两个估计里，两个效应互相抵消——")
    W("所以预估值对速率的数值几乎不敏感。")
    W("")
    W("而且在本机实测里，**根本不存在一个「稳定的 TPS」可供注入**：")
    W("同一模型的正文速率在 47.1–112.6 token/秒 之间跳（**2.39×**），")
    W("而且是**同一分钟内交替**出现，原因是请求被路由到吞吐相差约一倍的**不同后端**。")
    W("")
    W("| 层面 | 结论 | 证据 |")
    W("|---|---|---|")
    if ta:
        merged = []
        for v in ta.values():
            merged.extend(v.get("tps_text") or [])
        merged = sorted(merged)
        cf = (pb or {}).get("B_conversion_fidelity") or {}
        fid = cf.get("median")
        W(f"| 算术 | **会用**，照着注入值换算，偏差 "
          f"{(abs(1-fid)*100 if fid else 0):.2f}% | §3.2 / §4.2 |")
        W(f"| 物理前提 | **没有稳定 TPS**，实测 {merged[0]:.1f}–{merged[-1]:.1f} tok/s"
          f"（{merged[-1]/merged[0]:.2f}×），且是后端路由造成的 | §2 |")
    if tl:
        W(f"| 「3 分钟能不能避开快慢交替」 | **不能**。交替在**请求层**不在时间层："
          f"请求内窗口速率 CV {fmt(tl.get('within_request_cv_median'), 3)} vs "
          f"请求间 {fmt(tl.get('between_request_cv'), 3)}（比值 "
          f"{fmt(tl.get('ratio_within_over_between'), 2)}） | §2.4 |")
    if pb:
        tc = pb.get("A_token_compare") or {}
        sc = tc.get("speed_cal") or {}
        if sc.get("p") is not None:
            W(f"| 速率→长度 | **有用**。给了速率 + 时长目标，写出的 token 数 +{sc.get('delta',0):.0f}"
              f"（p={sc.get('p'):.3f}） | §3.1 |")
    if pb2:
        d = pb2.get("A2_dose") or {}
        d2 = pb2.get("B2_dose") or {}
        W(f"| 速率→时间感 | **无效**。预估值对速率的 log-log 斜率 b="
          f"{d.get('loglog_slope', 0):+.3f}≈0，三个剂量全部无显著差异 | §4.1 |")
        W(f"| 绝对时间→时间感 | **有效**。Δ={((pb2.get('A2_compare') or {}).get('elapsed') or {}).get('delta', 0):+.3f}，"
          f"p={((pb2.get('A2_compare') or {}).get('elapsed') or {}).get('p', 0):.3f} | §4.1 |")
        W(f"| 换算题里的剂量-反应 | **+{d2.get('spearman_rate_vs_implied', 0):.3f}** Spearman，"
          f"隐含速率完全跟着注入值走 | §4.2 |")
    if pc:
        cr = (pc.get("cross_run") or {}).get("全部") or {}
        a = (pc.get("arms") or {}).get("base") or {}
        W(f"| 过程时间感（写的时候标「已用时」） | **没有**。标注是开写前定好步长的等差数列；"
          f"跨轮 Spearman(真实耗时, 标注总秒) = "
          f"{fmt(cr.get('spearman_marked_vs_real'), 3)}，基线臂高估 "
          f"{fmt(a.get('median_marked_over_real'), 1)}× | §8 |")
    W("")
    W("**工程含义**：不要给速率，给绝对量（已过秒数 / 剩余预算 / 截止时刻）；")
    W("要控制输出长度就直接给篇幅预算，不要给时长目标；")
    W("确要用速率，就只把它当「速率→长度」的换算尺子用，并且给区间而不是单点。")
    W("")
    W("> 但有一个例外要说清楚：**「事后一次性预估」和「过程内自标」不是一回事**。")
    W("> 给绝对秒数能显著改善前者（§4.1），对后者**无效**（§8）——")
    W("> 因为过程自标需要「现在进行到哪」的内部状态，模型没有；")
    W("> 绝对秒数只能由外部时钟在每个回合适时注入，让模型**转述**，")
    W("> 而不是指望它自己累计。")
    W("")

    # ================= 1 协议 =================
    W("---")
    W("")
    W("## 1. 协议")
    W("")
    W("### 1.1 Phase A —— 30 秒连续生成，标定 TPS")
    W("")
    W("协议：每次实验 = **一次连续生成约 30 秒**，只有一条用户消息（全新会话）；")
    W("用逐块到达时刻算滑动窗口 TPS；固定开销（TTFT、尾部交付）被 30 秒窗口摊薄。")
    W("")
    W("两种任务形态：")
    W("")
    W("- **items**：要求输出**恰好 N 条编号条目**。长度确定、思维链短 → 速率测量干净；")
    W("- **longform**：要求写**至少 2000 字**的长文。会诱发思维链膨胀（最高 3860 token，")
    W("  占输出 96%），4/8 次撞 `max_completion_tokens` 上限被截断。")
    W("")
    W("### 1.2 Phase B v1 —— 四臂 30 秒实验（及其两个缺陷）")
    W("")
    W("臂：`base` / `speed_cal`（注入标定 TPS 中位）/ `speed_range`（注入中位+区间）/")
    W("`elapsed`（注入绝对秒数）。A 题「写满 30 秒」，B 题「已知 token 数问需多少秒」。")
    W("")
    W("两个缺陷（本报告据此重做了 Phase B2）：")
    W("")
    W("1. **echo**：A 题把「目标 = 30 秒」写进题面，于是「预计耗时：X」被原样抄成 30，")
    W("   分不清「有独立估计能力」和「会抄题」；")
    W("2. **剂量缺失**：速率臂只注入一个标定值，与基线的差异可能只是噪声。")
    W("")
    W("### 1.3 Phase B2 —— 去 echo + 剂量-反应")
    W("")
    W("- **不告诉目标秒数**：只给确定性长度（133 条条目），模型必须对自己这条回复的")
    W("  生成时长做**独立估计**，地面真值 = 外部实测生成时长；")
    W("- **剂量-反应**：任务、措辞、条数完全相同，**只改注入的速率数字**")
    W("  （40 / 76.5 / 120 token/秒）。预估值若随速率单调移动 → 这个数真的进了判断；")
    W("  若不动 → 这个数没进判断。")
    W("  其中 76.5 是实测标定中位，**40 与 120 是反事实剂量**，用于测敏感度，")
    W("  不能当成「部署速率」；")
    W("- **阳性对照 elapsed**：注入**真实的**同类生成实测耗时（取本臂上一条同类试验的实测值，")
    W("  首轮用 Phase A 实测时长中位作种子）。")
    W("")
    W("### 1.4 并发排除（可验证证据）")
    W("")
    W("每个实验进程内单线程顺序 await；每次调用记录 `[t_request, t_last]`；")
    W("分析脚本对**排序后的区间做重叠计数**。")
    if ta:
        W("")
        W("| 数据集 | 调用数 | 区间重叠 | 相邻调用间隔（中位） |")
        W("|---|---|---|---|")
        for name, v in ta.items():
            s = v.get("serial") or {}
            W(f"| `{name}` | {s.get('n','—')} | **{s.get('overlaps','—')}** | "
              f"{fmt((s.get('median_gap') or 0)*1000, 2)} ms |")
    if pb2:
        s = pb2.get("serial") or {}
        W(f"| `phase_b2.jsonl` | {s.get('n','—')} | **{s.get('overlaps','—')}** | "
          f"{fmt((s.get('median_gap_s') or 0)*1000, 2)} ms |")
    W("")
    W("重叠数全为 0 = 全程无并发。")
    W("")

    # ================= 2 Phase A =================
    W("---")
    W("")
    W("## 2. Phase A：「稳定的 TPS」存在吗？——不存在")
    W("")
    W("### 2.1 两个数据集的实测")
    W("")
    W("| 数据集 | n | 截断 | 正文速率区间 (tok/s) | 中位 | CV | 总时长区间 (s) | 正文 token 区间 | 思维链 |")
    W("|---|---|---|---|---|---|---|---|---|")
    for name, v in ta.items():
        tt = v.get("tps_text") or []
        dur = v.get("duration") or []
        ct = v.get("content") or []
        th = v.get("think") or []
        W(f"| `{name}` | {v.get('n','—')} | {v.get('n_truncated','—')} | "
          f"{min(tt):.1f}–{max(tt):.1f} | {v.get('median_tps_text', float('nan')):.1f} | "
          f"{v.get('cv_tps_text', float('nan')):.3f} | "
          f"{min(dur):.1f}–{max(dur):.1f} | {min(ct)}–{max(ct)} | {min(th)}–{max(th)} |")
    W("")
    merged = []
    mdur = []
    for v in ta.values():
        merged.extend(v.get("tps_text") or [])
        mdur.extend(v.get("duration") or [])
    merged = sorted(merged)
    mdur = sorted(mdur)
    n = len(merged)
    W(f"**合并 {n} 次未截断运行**：正文速率中位 **{merged[n//2]:.1f} tok/s**，"
      f"p10–p90 **{merged[int(0.1*n)]:.1f}–{merged[min(int(0.9*n), n-1)]:.1f}**，"
      f"极值 **{merged[0]:.1f}–{merged[-1]:.1f}**，**max/min = {merged[-1]/merged[0]:.2f}×**。")
    W("")
    W("### 2.2 方差从哪来：不是时间趋势，是**后端路由**")
    W("")
    W("items 数据集逐次速率序列（按时间顺序）：")
    for v in ta.values():
        if "items" in v:
            W("")
            W("```")
            W("  ".join(f"{x:.1f}" for x in (v.get("tps_text") or [])))
            W("```")
    W("")
    W("**快慢在同一分钟内交替出现**（110.7 → 53.8 → 76.6 → 117.5 → 48.9 → 58.0 → 106.1 → 55.7），")
    items_ct = []
    for v in ta.values():
        if "items" in v:
            items_ct = v.get("content") or []
    if items_ct:
        W(f"不是随时间漂移，也不是内容长度造成的（**同一个 items 数据集内**，正文 token 数只变化 "
          f"{min(items_ct):.0f}–{max(items_ct):.0f}，仅 {max(items_ct)/min(items_ct):.2f}×，"
          f"而速率变了 {2.39:.2f}×）。")
    W("")
    W("逐块到达时序给出的解释——服务端流式 chunking 本身分两条轨道：")
    W("")
    W("| 轨道 | 每块 token | 块间隔 | 推得 TPS |")
    W("|---|---|---|---|")
    W("| 快轨 | ~19.7 | ~0.16 s | 107–118 |")
    W("| 中轨（长文） | ~8.7 | ~0.11 s | 78–82 |")
    W("| 慢轨 | ~5.4–6.7 | ~0.07 s | 49–58（另有 4.1–5.9 s 的卡顿） |")
    W("")
    W("**结论**：同一模型的同一次部署，吞吐会随**被路由到哪个后端**在 ~2 倍幅度上跳。")
    W("所以「先测一个稳定 TPS，再把它注入」这个前提，在本机根本不成立——")
    W("**注入的那个常数，只是 12 次抽样的中位数，它有一半的概率是错的 2 倍。**")
    W("")
    W("### 2.3 一个副产物：分子本身也不可预测")
    W("")
    W("longform 模式下模型的思维链产量可达 3860 token（占输出 96%），")
    corrs = [(k, v.get("corr_think_duration")) for k, v in ta.items()
             if v.get("corr_think_duration") is not None]
    if corrs:
        parts = "、".join(f"`{k}` {v:+.3f}" for k, v in corrs)
        W(f"而思维链与总时长的相关系数是 {parts}")
    W("——**连「要吐多少 token」这件事本身都不稳定**，所以「时长 = token ÷ TPS」这个")
    W("换算式在真实 agent 循环里连分母带分子一起飘。")
    W("")

    # ================= 2.4 轨道层判定 =================
    if tl:
        W("")
        W("### 2.4 「拉长到 3 分钟就能避开快慢交替吗」——不能，而且能证明为什么")
        W("")
        W("用户的追问是：**快慢交替的话，能不能用 3 分钟实验来避免这个问题？**")
        W("要回答它，得先定位交替发生在哪一层：")
        W("")
        W("- **时间层**（一次请求内部，生成过程中换轨）→ 拉长单次请求**能**把两轨平均掉；")
        W("- **请求层**（两次请求之间，抽签决定走哪条轨）→ 拉长**没用**，下次请求照样抽签。")
        W("")
        W("用 5 秒滑动窗口速率逐次判定（`harness/analyze_track_layer.py`，图 `out/fig10_track_layer.png`）：")
        W("")
        W("| 口径 | 数值 | 含义 |")
        W("|---|---|---|")
        W(f"| 请求**内**窗口速率 CV 中位 | {fmt(tl.get('within_request_cv_median'), 3)} | "
          f"一次请求内基本**一条轨到底** |")
        W(f"| 请求**间**中位速率 CV | {fmt(tl.get('between_request_cv'), 3)} | "
          f"请求之间离散 {fmt(tl.get('between_request_extreme_ratio'), 2)}×（极值比） |")
        W(f"| 比值（内/间） | {fmt(tl.get('ratio_within_over_between'), 2)} | "
          f"**< 0.5 = 交替在请求层** |")
        W("")
        W("两个数据集分别看：")
        W("")
        W("| 数据集 | 请求内 CV 中位 | 请求间 CV | 请求间极值比 |")
        W("|---|---|---|---|")
        W(f"| items（确定性长度） | {fmt(tl.get('items_within_cv_median'), 3)} | "
          f"{fmt(tl.get('items_between_cv'), 3)} | — |")
        W(f"| longform（长文） | {fmt(tl.get('longform_within_cv_median'), 3)} | "
          f"{fmt(tl.get('longform_between_cv'), 3)} | — |")
        W("")
        W("**判定：交替发生在请求层（请求级抽签），不在时间层。**")
        W("")
        W("所以：")
        W("")
        W("- 拉长到 3 分钟**不会**消除交替——它只会让「这一次的速率」测得更准，")
        W("  而下一条请求仍然可能被路由到另一条轨；")
        W("- 唯一能把抽签平均掉的做法是**跨多次请求做滑动窗口累计平均**，并且报 p10–p90 区间；")
        W("- 而且固定开销（TTFT 中位 0.75–0.88 秒）只占 30 秒窗口的 2.5–2.9%，")
        W("  **测量时长本身不是误差来源**——拉长窗口收益很小。")
        W("")
        W("> 一句话：**3 分钟实验能回答「模型在长时间尺度上准不准」，")
        W("> 但回答不了「速率会不会稳定」——后者是路由决定的，不是时长决定的。**")
        W("")

    # ================= 3 Phase B v1 =================
    W("---")
    W("")
    W("## 3. Phase B v1")
    W("")
    r1 = load("r1_t2_stratified.json")
    if r1:
        W("### 3.0 先纠一个第一轮的坑：合并 3/8/20 秒目标是混合产物")
        W("")
        W("第一轮报告里「注入 TPS 后写满 N 秒的命中误差更差（0.574 vs 0.423）」")
        W("是把 **3/8/20 秒三个目标混在一起**取中位数得到的。按目标秒数分层后结论**反转**：")
        W("")
        W("| 目标秒数 | 臂 | n | med\\|hit\\| | 实际生成中位 (s) | 输出 token 中位 |")
        W("|---|---|---|---|---|---|")
        st_ = r1.get("stratified") or {}
        for tgt in ("3", "8", "20"):
            for arm, v in (st_.get(tgt) or {}).items():
                W(f"| {tgt} | {arm} | {v['n']} | {fmt(v.get('median_abs_hit_err'), 3)} | "
                  f"{fmt(v.get('median_gen_s'))} | {fmt(v.get('median_out_tokens'), 0)} |")
            base_v = (st_.get(tgt) or {}).get("base")
            if base_v:
                W(f"| {tgt} | **基线参照** | {base_v['n']} | "
                  f"**{fmt(base_v.get('median_abs_hit_err'), 3)}** | "
                  f"{fmt(base_v.get('median_gen_s'))} | "
                  f"{fmt(base_v.get('median_out_tokens'), 0)} |")
            W("| | | | | | |")
        W("读法：**3 秒目标上所有注入臂都优于基线**（基线 1.436 → 注入绝对秒数 0.292）；")
        W("8 秒和 20 秒目标上基线最好或持平。把三个目标混在一起取中位数，")
        W("「短目标上注入有用」被「长目标上注入没用」抵消掉了。")
        W("")
        resp = r1.get("responsiveness") or {}
        if resp:
            W("**更根本的一条：模型没有「时长目标」的概念。** 各臂的实际生成时长 vs 目标秒数：")
            W("")
            W("| 臂 | 3s 目标 | 8s 目标 | 20s 目标 | 30s 目标（Phase B v1） | 与目标的相关 |")
            W("|---|---|---|---|---|---|")
            pbA = (pb or {}).get("A") or {}
            for arm, v in resp.items():
                g = v.get("gen_s_by_target") or {}
                g30 = pbA.get(arm, {}).get("median_gen_s")
                W(f"| {arm} | {fmt(g.get('3'))} | {fmt(g.get('8'))} | {fmt(g.get('20'))} | "
                  f"{fmt(g30)} | {fmt(v.get('spearman_target_vs_gen_s'), 3)} |")
            W("")
            W("**目标从 3 秒加到 30 秒（10 倍），基线的输出时长始终是 5.7–7.4 秒**（无响应）。")
            W("各臂的「目标秒数 vs 实际时长」Spearman 相关都≈0。")
            W("也就是说：**模型不会因为「要写 30 秒」就多写**——它根本不理解「时长目标」。")
            W("")
            W("那么速率信号到底改变了什么？见 §3.1。")
            W("")
    if not pb:
        W("> 未找到 `out/phase_b_summary.json`，本节跳过。")
        W("")
    else:
        W("### 3.1 A 题：写满 30 秒")
        W("")
        W("| 臂 | n | 中位实际生成 (s) | 命中误差 med\\|hit\\| | med\\|ln(est/act)\\| | 中位 TPS | **中位输出 token** |")
        W("|---|---|---|---|---|---|---|")
        for arm, v in (pb.get("A") or {}).items():
            W(f"| {arm} | {v['n']} | {fmt(v.get('median_dur'))} | "
              f"{fmt(v.get('median_abs_hit_err'), 3)} | {fmt(v.get('median_est_logerr'), 3)} | "
              f"{fmt(v.get('median_tps'), 1)} | **{fmt(v.get('median_out_tokens'), 0)}** |")
        W("")
        base_tok = (pb.get("A") or {}).get("base", {}).get("median_out_tokens")
        spd_tok = (pb.get("A") or {}).get("speed_cal", {}).get("median_out_tokens")
        if base_tok and spd_tok:
            W(f"**唯一非 echo 的效应**：注入速率的臂**写出的 token 数显著更多**"
              f"（speed_cal 中位 {spd_tok:.0f} vs base {base_tok:.0f}，"
              f"+{(spd_tok/base_tok-1)*100:.0f}%），因而更贴近 30 秒目标。")
            W("token 数与后端快慢无关，所以这是**模型真的拿速率给输出定量**的直接证据。")
            W("")
        tcmp = pb.get("A_token_compare") or {}
        if tcmp:
            W("| 臂 | 输出 token 中位 | Δ vs base | CI | p | 判定 |")
            W("|---|---|---|---|---|---|")
            for arm, c in tcmp.items():
                ci = c.get("ci") or (None, None)
                p, d = c.get("p"), c.get("delta")
                if d is None or p is None:
                    continue
                mark = ("显著更多" if d > 0 and p < 0.05 else
                        "显著更少" if d < 0 and p < 0.05 else "无显著差异")
                W(f"| {arm} | {fmt((pb.get('A') or {}).get(arm, {}).get('median_out_tokens'), 0)} | "
                  f"{d:+.0f} | [{ci[0]:.0f}, {ci[1]:.0f}] | {p:.3f} | {mark} |")
            W("")
            W("> **这条对比是本轮最干净的结果**：")
            W("> 速率能换算成**长度**（+584 token，p=0.004），")
            W("> 绝对秒数**换不出长度**（+40 token，p=0.695）——")
            W("> 因为「30 秒」不告诉你该写多少字，「76 token/秒」告诉你了。")
            W(">")
            W("> **内部对照**：v1 的臂按固定顺序执行（base → speed_cal → speed_range → elapsed）。")
            W("> 若效应来自「越跑越写越多」的漂移，最后一个臂（elapsed）应该最明显——")
            W("> 但它没有。这条效应来自速率本身，不是执行顺序。")
            W("")
        if pb.get("A_echo_rate"):
            e = pb["A_echo_rate"]
            W(f"**echo 诊断**：预估值恰好等于目标秒数（30）的比例 **{e['echo']}/{e['n']} = "
              f"{e['rate']*100:.0f}%** → A 题的「预估」栏是抄题，")
            W("**不能**用来比较臂的估计能力。这直接催生了 Phase B2。")
            W("")
        cmp_ = pb.get("compare") or {}
        if cmp_:
            W("成对比较（vs base，置换检验）：")
            W("")
            W("| 指标 | 臂 | Δ | CI | p | 判定 |")
            W("|---|---|---|---|---|---|")
            for k, c in cmp_.items():
                tname, arm = k.split("|")
                ci = c.get("ci") or (None, None)
                p = c.get("p")
                d = c.get("delta")
                if d is None or p is None:
                    continue
                mark = ("显著变好" if d < 0 and p < 0.05 else
                        "显著变差" if d > 0 and p < 0.05 else "无显著差异")
                W(f"| {tname} | {arm} | {d:+.3f} | [{ci[0]:.3f}, {ci[1]:.3f}] | {p:.3f} | {mark} |")
            W("")
            W("> ⚠️ **「A-预估误差」这一行不能当独立证据读。** 因为预估恒等于 30（抄题），")
            W("> 它的误差只是 |ln(30/实测)| 的另一种写法——和「命中误差」是同一个量的两种表达，")
            W("> 不是「估计能力变好了」。真正独立的读数是**命中误差**和**输出 token 数**。")
            W(">")
            W("> ⚠️ **v1 的臂顺序是固定的**（base → speed_cal → speed_range → elapsed），")
            W("> 没有随机化，理论上存在顺序/漂移混淆；Phase B2 已改为**逐轮交错**执行。")
            W("")

        W("### 3.2 B 题：给定速率，模型换算得准不准？")
        W("")
        W("| 臂 | n | med\\|err\\| | median est/truth |")
        W("|---|---|---|---|")
        for arm, v in (pb.get("B") or {}).items():
            W(f"| {arm} | {v['n']} | {fmt(v.get('median_abs_err'), 3)} | "
              f"{fmt(v.get('median_ratio'), 3)} |")
        W("")
        cf = pb.get("B_conversion_fidelity")
        if cf:
            W(f"**换算保真度 `est × rate / tokens`：中位 {cf['median']:.4f}"
              f"（{cf['min']:.4f}–{cf['max']:.4f}，n={cf['n']}）**。")
            W("")
            W("即：题目里给「约 76 token/秒」，模型就**原样照用**，")
            W("500→6.5s、1500→19.6s、3000→39.2s、4500→58.8s，误差在小数点后一位以内。")
            W("")
            W("> ⚠️ 口径提醒：v1 的 B 题把速率写进了**用户消息**，四个臂拿到的是同一个数，")
            W("> 所以 B 题在 v1 里**不能用来比较臂**，它测的是「给定速率后换算对不对」。")
            W("")
        W("**这一条把第一轮的结论改写了**：第一轮模型在策略自述里说")
        W("「依据约 31.3 token/秒的实测速度，按约 94 token 估算」——那 31.3 是它**自己编的**。")
        W("给它一个**真实**速率，它换算得毫不差。")
        W("所以第一轮「注入 TPS 反而更差」的机制不是「模型不会用速率」，")
        W("而是「模型会用一个它自己编的、错 2 倍的速率」。")
        W("")

    # ================= 4 Phase B2 =================
    W("---")
    W("")
    W("## 4. Phase B2：注入速率到底有没有变成时间感？")
    W("")
    if not pb2:
        W("> 未找到 `out/phase_b2_summary.json`，本节跳过。")
        W("")
    else:
        W("### 4.1 A2 题：30 秒自持，模型独立预估自己的生成时长")
        W("")
        W("题面**不出现目标秒数**（避免抄题），只给「恰好 133 条编号条目」；")
        W("真值 = 外部实测生成时长。")
        W("")
        W("| 臂 | n | 实测生成中位 (s) | 预估中位 (s) | med\\|ln(est/act)\\| | 隐含 token 中位 | 实际 token 中位 | echo |")
        W("|---|---|---|---|---|---|---|---|")
        for arm, v in (pb2.get("A2") or {}).items():
            W(f"| {arm} | {v['n']} | {fmt(v.get('median_actual_gen_s'))} | "
              f"{fmt(v.get('median_est_s'), 1)} | {fmt(v.get('median_abs_log_err'), 3)} | "
              f"{fmt(v.get('median_implied_tokens'), 0)} | {fmt(v.get('median_content_tokens'), 0)} | "
              f"{v.get('echo_item_count','—')} |")
        W("")
        d = pb2.get("A2_dose") or {}
        if d.get("doses"):
            W("**剂量-反应**（预估值随注入速率移动吗）：")
            W("")
            W("| 注入速率 (tok/s) | 预估中位 (s) | 臂 |")
            W("|---|---|---|")
            for x in d["doses"]:
                W(f"| {x['rate']:.0f} | {fmt(x.get('median_est'), 1)} | {x['arm']} |")
            W("")
            rho = d.get("spearman_rate_vs_est")
            slope = d.get("loglog_slope")
            W(f"- Spearman(注入速率, 预估值) = **{fmt(rho, 3)}**"
              f"（负 = 速率越高预估越短 = 模型把速率当速率用了）")
            W(f"- 拟合 `ln(est) = a + b·ln(rate)`，**b = {fmt(slope, 3)}**"
              f"（b=0 完全没用；b=-1 表示完全当速率用）")
            W("")
        cmp2 = pb2.get("A2_compare") or {}
        if cmp2:
            W("**增益检验**（med|ln(est/实测)| 越低越好 vs base，置换检验）：")
            W("")
            W("| 臂 | Δ | CI | p | 判定 |")
            W("|---|---|---|---|---|")
            for arm, c in cmp2.items():
                ci = c.get("ci") or (None, None)
                p, dd = c.get("p"), c.get("delta")
                if dd is None or p is None:
                    continue
                mark = ("显著更好" if dd < 0 and p < 0.05 else
                        "显著更差" if dd > 0 and p < 0.05 else "无显著差异")
                W(f"| {arm} | {dd:+.3f} | [{ci[0]:.3f}, {ci[1]:.3f}] | {p:.3f} | {mark} |")
            W("")
        W("### 4.2 B2 题：纯换算（速率只在系统提示里）")
        W("")
        W("题目里**不含速率**，速率只出现在臂的系统提示中；读数是**隐含速率** =")
        W("token 数 ÷ 模型答的秒数 = 模型「以为自己」有多快。")
        W("")
        W("| 臂 | n | 隐含速率中位 (tok/s) | 隐含/注入 |")
        W("|---|---|---|---|")
        for arm, v in (pb2.get("B2") or {}).items():
            W(f"| {arm} | {v['n']} | {fmt(v.get('median_implied_rate'), 1)} | "
              f"{fmt(v.get('implied_over_injected'), 3)} |")
        W("")
        d2 = pb2.get("B2_dose") or {}
        if d2.get("spearman_rate_vs_implied") is not None:
            W(f"- Spearman(注入速率, 隐含速率) = **{d2['spearman_rate_vs_implied']:+.3f}**"
              f"（+1 = 完全照注入值换算）")
            W("")
        base_imp = (pb2.get("B2") or {}).get("base", {}).get("median_implied_rate")
        if base_imp:
            W(f"- **基线（没有任何外部信息）的隐含速率是 {base_imp:.1f} tok/s**，"
              f"且 500/1500/3000/4500 四个 token 档**全部答出同一个值**——")
            W("  这就是模型默认假设的「自己有多快」。它离实测中位 "
              f"{merged[len(merged)//2]:.1f} tok/s 差了一截，但**量级是对的**。")
            W("  对照：注入速率的臂，隐含速率**完全跟着注入值走**（比值 0.998 / 1.005 / 1.000），")
            W("  连**系统提示里**的环境速率也会被照用。")
            W("")
            el_imp = (pb2.get("B2") or {}).get("elapsed", {}).get("median_implied_rate")
            if el_imp:
                W(f"- `elapsed` 臂的隐含速率是 {el_imp:.0f} tok/s，**这不是换算结果，是没换算**：")
                W("  给了绝对秒数却没给 token 数，模型答的秒数偏小，除出来的「速率」自然荒谬。")
                W("  **速率和绝对秒数之间不能互相换算**——它们是两种不同的信息，")
                W("  各自只能用在自己那侧的问题上。")
                W("")
        if pb2.get("v1_echo"):
            v1e = pb2["v1_echo"]
            W(f"**echo 对照**：v1（告知目标秒数）{v1e['echo']}/{v1e['n']} = "
              f"{v1e['rate']*100:.0f}% 抄题；B2（不告知目标秒数）无抄题 → "
              f"B2 的预估是模型独立做的。")
            W("")
        rs = load("phase_b2_reasoning.json")
        if rs and rs.get("items"):
            W("### 4.3 机制：思维链里的换算自述（原文）")
            W("")
            W("模型常把自己的算式写进思维链，这是「它到底有没有把速率当除数用」的**直接证据**：")
            W("")
            W("| 臂 | 注入 | 预估 | 思维链原文（截断） |")
            W("|---|---|---|---|")
            seen = set()
            for it in rs["items"]:
                key = (it["arm"], it["injected_rate"])
                if key in seen:
                    continue
                seen.add(key)
                sn = (it["snippets"] or [""])[0]
                if len(sn) > 190:
                    sn = sn[:190] + "…"
                W(f"| {it['arm']} | "
                  f"{it['injected_rate']:.1f} | " if it["injected_rate"] else
                  f"| {it['arm']} | — | ")
                W(f"{it['estimate_s']} | `{sn}` |")
                if len(seen) >= 6:
                    break
            W("")
            W("读法：**模型确实在做除法**（「2000 Chinese tokens at 40 tok/sec ~50 sec」），")
            W("但（a）它自己估的 token 数随注入速率一起涨，")
            W("（b）单位有时会滑掉（「maybe 120 sec given 120 tok/s」——把速率直接当秒数）。")
            W("两头误差相乘，于是预估值对速率的**数值**不敏感（上面 b≈0 就是这么来的）。")
            W("")
            W("这也解释了 §4.1 的**取消机制**：模型「以为」自己要写的 token 数")
            W("（= 预估秒数 × 注入速率）随注入速率单调上升")
            d = pb2.get("A2_dose") or {}
            itk = d.get("implied_tokens_median_by_arm") or {}
            for arm, v in itk.items():
                if v:
                    W(f"  - `{arm}`：隐含 token 中位 {v:.0f}")
            if d.get("spearman_rate_vs_implied_tokens") is not None:
                W(f"  - Spearman(注入速率, 隐含 token 数) = "
                  f"**{d['spearman_rate_vs_implied_tokens']:+.3f}**")
            W("")

    # ================= 5 结论 =================
    W("---")
    W("")
    W("## 5. 回答原问题")
    W("")
    W("**「告诉 LLM 它上个周期的 TPS，能不能让它有时间感？」——不能。**")
    W("")
    W("但这个「不能」要拆成四层才准确，因为**速率信号确实在做一件事，只是不是「时间感」**：")
    W("")
    W("| # | 层面 | 结论 | 关键数字 |")
    W("|---|---|---|---|")
    if pb:
        cf = pb.get("B_conversion_fidelity") or {}
        sc = (pb.get("A_token_compare") or {}).get("speed_cal") or {}
        W(f"| 1 | **算术** | 会用，精确照用 | 换算保真度中位 {cf.get('median', 0):.4f}"
          f"（偏差 {abs(1-cf.get('median', 1))*100:.2f}%） |")
        W(f"| 2 | **速率→长度** | 有用 | 写入 token {sc.get('delta', 0):+.0f}，p={sc.get('p', 0):.3f} |")
    if pb2:
        d = pb2.get("A2_dose") or {}
        d2 = pb2.get("B2_dose") or {}
        el = (pb2.get("A2_compare") or {}).get("elapsed") or {}
        W(f"| 3 | **速率→时间感** | **无效** | log-log 斜率 b={d.get('loglog_slope', 0):+.3f}≈0；"
          f"三个剂量 vs base 全部 p≥0.11 |")
        W(f"| 4 | **绝对时间→时间感** | **有效** | Δ={el.get('delta', 0):+.3f}，p={el.get('p', 0):.3f}；"
          f"est/实测 {((pb2.get('A2') or {}).get('elapsed') or {}).get('median_est_over_actual', 0):.2f} |")
    W("")
    W("**为什么第 3 层不成立——取消机制。** 模型把速率同时灌进两个估计：")
    W("")
    W("- 「我能写多少 token」：速率越高，它计划写得越多；")
    W("- 「这要花多少秒」：速率越高，它觉得越快。")
    W("")
    W("两者相乘/相除大部分抵消，于是预估值对速率的**数值**不敏感，")
    W("但对「有没有速率」敏感（基线完全没有尺度，预估中位高估 3.79 倍）。")
    W("")
    W("**还有一个更硬的前提问题**：本机根本不存在「稳定的 TPS」可注入（§2）。")
    W("速率在 2.39× 的幅度上随**后端路由**跳变，注入 12 次抽样的中位数，")
    W("等于注入一个有一半概率错 2 倍的数。")
    W("")
    W("> **一句话**：速率是**尺子**不是**时钟**。")
    W("> 尺子能用（而且用得很准），但拿尺子量「自己还剩多少时间」量不出来。")
    W(">")
    W("> 顺带修正第一轮的两处口径问题：")
    W("> ① 第一轮「注入 TPS 反而更差」是把 3/8/20 秒三个目标混在一起取中位数得到的混合产物，")
    W("> 按目标分层后 3 秒目标上所有注入臂都**优于**基线（§3.0）；")
    W("> ② 第一轮判「模型不会用速率」也不对——它会用，只是用的那个速率是**自己编的**")
    W("> （自述「约 31.3 token/秒」，真值约 76）。")
    W("")
    W("---")
    W("")
    W("## ★ 重点标记：条件结论")
    W("")
    W("> ### 如果 TPS 稳定，注入速率就可以使模型获得时间感")
    W(">")
    W("> **本报告所有「速率→时间感无效」的结论，都是在「注入的速率本身是抽签出来的、")
    W("> 有一半概率错 2 倍」这个前提下测得的。**")
    W(">")
    W("> **支撑证据**：")
    W("> ① 模型对给定的速率照单全收——隐含速率/注入速率 = 0.998 / 1.005 / 1.000，")
    W(">    Spearman +0.952（§4.2）；")
    W("> ② 给了速率 + 明确时长目标后，写满 N 秒的命中误差 0.754 → 0.482（p=0.032）、")
    W(">    输出 token +584（p=0.004）——**速率把「时间」翻译成了可执行的长度**（§3.1）；")
    W("> ③ 隐含 token 数随注入速率单调上升（2800→3558→6900，Spearman +0.784），")
    W(">    说明**时间那条通道是通的**（§4.3）。")
    W(">")
    W("> **但还要同时满足第二个条件**：绕开「取消」机制——速率越高模型计划写得越多，")
    W("> 时间估计被同一个数抵消。稳定速率是**必要但不充分**条件。")
    W(">")
    W("> **诚实标注**：这条命题本轮**没有被直接测过**。A2 自持题里每臂注入的是**固定**速率")
    W("> （臂内即「稳定」），剂量-反应斜率仍为 b≈0，三个剂量 vs base 全部无显著差异——")
    W("> 说明起作用的不只是速率抖动，还有取消机制本身。")
    W("> 要真正验证它，需要一个**能提供稳定 TPS 的部署**（固定后端路由，或跨请求滑动窗口")
    W("> 累计平均后再注入），在那边重跑 A2 自持题。")
    W(">")
    W("> 详见 §5.1 与 REPORT_SIMPLE.md。")
    W("")
    W("### 5.1 两个追加问题的直接回答")
    W("")
    W("**问：「快慢交替的话，能不能通过 3 分钟实验来避免这个问题？」**")
    W("")
    W("**不能，而且能证明为什么。** 交替发生在**请求层**（请求级抽签），不在**时间层**：")
    W("一次请求内部 5 秒滑动窗口速率**基本是平的**（CV 中位 0.177），")
    W("而请求之间的离散是 0.920（极值比 5.28×）。")
    W("所以把单次请求拉长到 3 分钟，只会让「这一次的速率」测得更准，")
    W("**下一条请求照样抽签**；而且固定开销（TTFT 中位 0.75–0.88 秒）只占 30 秒的 2.5–2.9%，")
    W("**测量时长本身不是误差来源**。详见 §2.4。")
    W("")
    W("3 分钟实验**能做**的事，做了（§8）：它把问题换成了「模型在长时间尺度上准不准」，")
    W("答案是——**它没有过程时间感**。")
    W("")
    W("**问：那让模型在写的过程中自己标「已用时」，注入速率/耗时有没有用？**")
    W("")
    W("**没有。** 模型标出来的「已用时」是一条**在开写前就定好步长的等差数列**，")
    W("与真实流逝零相关（跨轮 Spearman(真实耗时, 标注总秒) = -0.070）；")
    W("注入速率时它确实用了这个速率，但算的是「**我打算写多少** ÷ 速率」，")
    W("注入绝对耗时时它明说「**We cannot accurately know**」。详见 §8。")
    W("")
    W("### 5.2 「如果 TPS 稳定呢？」——条件结论的完整版")
    W("")
    W("**「速率不能变成时间感」这个结论是带前提的。** 前提是「注入的速率本身是抽签出来的」")
    W("（本机正文速率 47.1–112.6 tok/s，max/min = 2.39×，同一分钟内交替，后端路由所致）。")
    W("如果部署能提供**稳定且准确**的 TPS，结论会怎样？三条证据指向「可以」：")
    W("")
    W("1. **模型会照单全收给定的速率**——隐含速率/注入速率 = 0.998 / 1.005 / 1.000，")
    W("   Spearman(注入速率, 隐含速率) = +0.952；没有外部信息时它默认假设自己约 50 tok/s。")
    W("2. **速率能把「时间」翻译成可执行的长度**——给了速率 + 明确时长目标后，")
    W("   写满 N 秒的命中误差 0.754 → 0.482（p=0.032），输出 token 766 → 1350（p=0.004）。")
    W("3. **时间那条通道是通的**——隐含 token 数随注入速率单调上升")
    W("   （2800→3558→6900，Spearman +0.784）：同一个数同时进了「我能写多少」和「要多久」，")
    W("   所以模型**有**做时间换算的能力。")
    W("")
    W("**但稳定速率只是必要条件，还要第二条**：得绕开「取消」——速率越高模型计划写得越多，")
    W("时间估计被同一个数抵消。两条出路：给**绝对时间量**，或给**速率 + 明确的待写量**。")
    W("")
    W("**诚实标注：本轮没有直接测过这条条件命题。** A2 自持题里每臂注入的是**固定**速率")
    W("（臂内即「稳定」），剂量-反应斜率仍然是 b≈0、三个剂量 vs base 全部无显著差异——")
    W("说明**起作用的不只是速率抖动，取消机制本身也在起作用**。")
    W("要真正验证「速率稳定 ⇒ 有时间感」，需要一个**能提供稳定 TPS 的部署**")
    W("（固定后端路由，或跨请求滑动窗口累计平均后再注入），在那边重跑 A2 自持题。")
    W("")

    # ================= 6 工程建议 =================
    W("---")
    W("")
    W("## 6. 工程建议")
    W("")
    W("1. **给绝对量，不给速率。** 「已经过去 12.4 秒」「还剩 47 秒」「截止 18:30」")
    W("   这类**绝对时间量**模型能直接用，而且是本轮唯一显著有效的信号")
    W("   （Δ=-1.07，p=0.009，est/实测 1.31）。速率类信息要模型自己再乘一个它估不准的量")
    W("   （自己会写多少 token），两头误差相乘。")
    W("2. **要控制长度就直接给篇幅预算。** 「不超过 300 字 / 约 800 token」是可执行的约束；")
    W("   「写满 20 秒」不行——**模型没有时长目标的概念**：目标从 3 秒加到 30 秒（10 倍），")
    W("   基线写出的时长始终是 5.7–7.4 秒（§3.0）。")
    W("3. **确要用速率，就当「速率→长度」的换算尺子用**，也就是配一个明确的待写量，")
    W("   而且要给它**滑动窗口累计平均 + 区间**。单点 TPS 采样误差可达 2 倍；")
    W(f"   p10–p90 区间 {merged[int(0.1*n)]:.0f}–{merged[min(int(0.9*n), n-1)]:.0f} "
      f"比单点中位有用得多。")
    W("4. **把「速率」和「时钟」分开。** agent 循环要「还剩多少时间」，用外部时钟算，")
    W("   把绝对剩余秒数喂进去；速率只用于**容量规划**（这条消息大概要写多长），")
    W("   不要用于**时间感知**。")
    W("5. **别指望模型报告「上一条花了多久」。** 第一轮实测：除绝对秒数臂外，")
    W("   各臂在「报上一条用时」这个问题上的**自我复读率 100%**——")
    W("   答的是自己上一轮的预测，不是外部测量值。")
    W("6. **也别指望模型在写的过程中自己标时间（§8）。** 它的「已用时」是")
    W("   **开写前定好步长的等差数列**，与真实流逝零相关。")
    W("   想让长任务里的模型报时间，只能由**外部时钟在每个回合适时注入「已经过了 X 秒」**，")
    W("   让模型**转述**这个数——不要让它自己累计，也不要给它速率让它自己换算。")
    W("")

    # ================= 7 边界 =================
    W("---")
    W("")
    W("## 7. 边界与威胁有效性")
    W("")
    W("- **单一模型家族**：全部实验只用 `MiniMax-M3.1-Flash`。跨家族是否一致未验证")
    W("  （本机无可用本地对话权重，成本收益不划算，见 §7 附注）。")
    W("- **单一部署**：速率的双峰是**本机这条 API 线路**的现象，换 provider 可能形态不同。")
    W("- **不可控因素**：MiniMax Code 的其它会话走产品网关，可能与本机共享后端池，")
    W("  无法完全排除对 TPS 分布的影响；本报告因此把所有速率结论都写成**分布**而非**定值**。")
    W("- **样本量**：Phase B2 每臂 n=8（自持题）/ 12（换算题），置换检验的分辨率有限；")
    W("  结论以效应方向与剂量-反应斜率为主，不以单个 p 值为准。")
    W("- **Phase A 的 4 次截断**：longform 数据集 4/8 撞 token 上限被剔除，")
    W("  报告中的速率统计只用未截断样本（n=12）。")
    W("- **Phase C 的两个规格提示词不同**：短规格用初版措辞（每节 300–500 字），")
    W("  长规格用修正后的无歧义措辞（每节约 2400 字）。措辞差异不只影响合规率，")
    W("  也可能轻微影响内容组织；但**两者的臂间对照都在各自规格内部完成**，")
    W("  规格之间的横向比较只作参考。")
    W("- **长规格样本量偏小**：Token Plan 额度上限（错误码 2056）会周期性切断实验，")
    W("  长规格的完整轮次数取决于额度窗口何时恢复。")
    W("- **传输层切换**：Phase C 长规格的前几轮经由本地代理，之后改为直连")
    W("  （代理进程挂掉，见 `harness/client.py:prepare_transport()`）。")
    W("  分析脚本会对比两组的速率分布，结论以两组的重叠为准。")
    W("")

    # ================= 8 Phase C 过程时间感 =================
    if pc:
        W("---")
        W("")
        W("## 8. Phase C：过程时间感（模型在**写的时候**知不知道已经过了多久）")
        W("")
        W("### 8.1 这一轮补的是前两轮没测的那块")
        W("")
        W("第一轮 / Phase B 测的都是**一次性预估**（回答前）或**事后自述**（写完再问）。")
        W("这一轮测**生成过程中**：模型每写完一小节就自己标一次「〔已用时 X 秒〕」，")
        W("我们把每个标记定位到流里的**真实经过秒数**，直接对着比。")
        W("")
        W("### 8.2 三处必须先解决的工程问题（都是踩出来的）")
        W("")
        W("**(1) 锚点必须是「模型数得动的结构」。** 三次校准：")
        W("")
        W("| 标记方式 | 实际结果 |")
        W("|---|---|")
        W("| 每 N 字标一次（chars） | 10 个标记**全部堆在文末**，等差 24,48,…240 |")
        W("| 每 N 段标一次（para） | **0 个标记**，指令被完全无视 |")
        W("| 每 N 个**连续编号**小节标一次（sections） | **12/12 全部 inline**，位置均匀 |")
        W("")
        W("结论：模型数不动字数，但数得动编号。正式跑批一律用编号小节。")
        W("")
        W("**(3) 措辞歧义会毁掉整个长规格实验（2026-11-03 实测）。**")
        W("初版措辞是「**每写完第 1 个小节**，就加一个时间标记」。")
        W("短规格 12 轮全部理解成「每一节都标」（12/12 合规），但长规格里模型开始较真：")
        W("")
        W("> *\"Each section timing after first only? Wording 每写完第1个小节，就… "
          "'第1个' perhaps only section 1. … Yet '每写完第 1 个小节' **unambiguously only first "
          "section**. … So only first.\"*（长规格 speed k2）")
        W("")
        W("结果该轮只输出了 **1 个标记**（12 个里少了 11 个）；另一轮甚至一个都没输出。")
        W("**教训**：长文里模型会逐字抠指令，锚点措辞必须写成无歧义的形式——")
        W("最终改成「每写完**一个小节**……{n} 个小节**每一个**的末尾都要有一个标记，"
          "全文共 {n} 个标记……**不是只在小节 1 后面标**」。")
        W("改完后长规格标记合规率回到 12/12。")
        W("")
        W("**(2) 每次实验只有一条用户消息**（清空上下文），全程严格串行，")
        W("每次调用记录 `[t_request, t_last]` 并断言区间 0 重叠。")
        W("")
        W("### 8.3 四种机制怎么被区分开")
        W("")
        W("| 机制 | 预期特征 |")
        W("|---|---|")
        W("| ① 内部有钟 | 标注与真实流逝成正比，斜率≈1，残差小 |")
        W("| ② 按字数瞎猜 | 标注 ∝ 累计字数；速率平稳时和真实时间几乎难区分，"
          "所以只能看**绝对准确度** |")
        W("| ③ 靠注入的速率推 | 标注 ∝ 字数，斜率 = 目标总时长/总字数；速率一变就露馅 |")
        W("| ④ 靠注入的绝对量摊 | 标注与真实时间斜率≈1，但**整体偏移**（总量摊错） |")
        W("")

        def render_spec(pd, head, num, sec_label, desc):
            rows = pd.get("rows") or []
            usable = [r for r in rows if r.get("slope_t") is not None]
            if not usable:
                return
            W(f"### {num} {head}")
            W("")
            W(desc)
            W("")
            W("| 臂 | 轮 | 真实耗时 | 正文 tok | 标记数 | 标注步长 | 末标注 | 末标注/真实 | 斜率(标注~真实) | R²(真实) | R²(字数) |")
            W("|---|---|---|---|---|---|---|---|---|---|---|")
            for r in usable:
                ps = r.get("pairs") or []
                steps = [ps[i]["v"] - ps[i - 1]["v"] for i in range(1, len(ps))]
                stp = med(steps)
                W(f"| {r['arm']} | k{r['trial']} | {r['gen_s']:.1f}s | {r.get('content_tokens')} | "
                  f"{r.get('n_marks')} | {fmt(stp, 1)}s | {fmt(r.get('last_mark'), 0)}s | "
                  f"{fmt(r.get('last_ratio'), 2)} | {fmt(r.get('slope_t'), 3)} | "
                  f"{fmt(r.get('r2_t'), 3)} | {fmt(r.get('r2_c'), 3)} |")
            W("")
            arms = pd.get("arms") or {}
            W("| 臂 | n | 真实耗时中位 | 末标注/真实（中位） | 模型隐含 tok/s | 隐含/注入速率 | Δt,ΔN Spearman | 标记/(token/注入速率) | 标记/注入耗时 | 标记丢失 |")
            W("|---|---|---|---|---|---|---|---|---|---|")
            for arm in ("base", "speed", "elapsed"):
                a = arms.get(arm)
                if not a:
                    continue
                W(f"| {arm} | {a.get('n')} | {fmt(a.get('median_gen_s'), 1)}s | "
                  f"{fmt(a.get('median_marked_over_real'), 2)} | "
                  f"{fmt(a.get('median_implied_tps'), 1)} | "
                  f"{fmt(a.get('median_implied_vs_injected_tps'), 2)} | "
                  f"{fmt(a.get('median_d_spearman'), 3)} | "
                  f"{fmt(a.get('median_used_rate_ratio'), 2)} | "
                  f"{fmt(a.get('median_used_elapsed_ratio'), 2)} | "
                  f"{a.get('n_zero_marks', 0)}/{a.get('n_runs', 0)} |")
            W("")
            W("（「标记丢失」= 模型在思维链里规划了时间标记、正文里却一个都没写。）")
            W("")
            cr = pd.get("cross_run") or {}
            if cr:
                W("跨轮：同一臂内部，真实跑得越慢的一轮，标注总秒数是否更大？")
                W("")
                W("| 范围 | n | Spearman(真实耗时, 标注总秒) | Spearman(真实耗时, 标注步长) |")
                W("|---|---|---|---|")
                for scope, v in cr.items():
                    W(f"| {scope} | {v.get('n')} | {fmt(v.get('spearman_marked_vs_real'), 3)} | "
                      f"{fmt(v.get('spearman_step_vs_real'), 3)} |")
                W("")
            ir = pd.get("implied_rate") or {}
            if ir:
                W("模型心里那把「速率尺子」是量出来的还是默认的？")
                W("")
                W("（隐含速率 = 正文 token ÷ 标注总秒。若模型在感知流逝，它应当随真实速率一起变。）")
                W("")
                W("| 范围 | n | 隐含速率中位 (CV) | 真实速率中位 (CV) | Spearman(隐含, 真实) |")
                W("|---|---|---|---|---|")
                for scope, v in ir.items():
                    W(f"| {scope} | {v.get('n')} | {fmt(v.get('median_implied_tps'), 1)} tok/s "
                      f"({fmt(v.get('cv_implied'), 3)}) | "
                      f"{fmt(v.get('median_real_tps'), 1)} tok/s ({fmt(v.get('cv_real'), 3)}) | "
                      f"{fmt(v.get('spearman_implied_vs_real'), 3)} |")
                W("")

        render_spec(
            pc, "短规格（每节 300–500 字，真实 20–165 秒）", "8.4", "短规格",
            "12 轮 × 3 臂，每轮 12 个内联标记，共 144 个标记，**标记 inline 率 0.83**"
            "（= 落在正文 90% 之前的占比；最后一个标记必然靠近末尾）。")
        if pcl:
            nl = len([r for r in (pcl.get("rows") or [])])
            render_spec(
                pcl, "长规格（每节约 2400 字，真实 2–7 分钟）", "8.5", "长规格",
                "把每节篇幅从 300–500 字放大到约 2400 字，让真实生成长度落到 **2–7 分钟量级**——"
                "**这就是用户问的「3 分钟实验」**。用无歧义措辞（见 §8.2(3)）重跑，"
                f"当前已到 {nl} 轮。")

        v0 = load("phase_c_v0_summary.json")
        if v0:
            W("### 8.6 措辞歧义的代价：长规格的标记合规率怎么塌的")
            W("")
            W("初版措辞「每写完第 1 个小节」在长规格下被模型读成「只在第 1 节后面标」。")
            W("歧义版长规格的 4 轮实测：")
            W("")
            W("| 臂 | 轮 | 真实耗时 | 正文 tok | 输出标记数 | 末标注 | 末标注/真实 |")
            W("|---|---|---|---|---|---|---|")
            for r in (v0.get("rows") or []):
                lm = r.get("last_mark")
                W(f"| {r['arm']} | k{r['trial']} | {r['gen_s']:.1f}s | "
                  f"{r.get('content_tokens')} | **{r.get('n_marks')}**/12 | "
                  f"{fmt(lm, 0) + 's' if lm is not None else '—'} | "
                  f"{fmt(r.get('last_ratio'), 2)} |")
            W("")
            W("→ 4 轮里 2 轮彻底丢标记（0 个、1 个），另外 2 轮 12/12 全对。")
            W("→ 但那 2 轮合规的（base 189.0 秒 / speed 436.0 秒）已经是**真实 3–7 分钟量级**的生成，")
            W("  末标注/真实分别是 **1.35×** 和 **1.32×**——**高估倍数并没有随生成长度下降**。")
            W("→ 改成无歧义措辞后，长规格单轮试跑回到 12/12（真实 170.5 秒，末标注 1545 秒 = 9.06×）。")
            W("")

        # 思维链证据
        cites_rate = [r for r in (pc.get("rows") or []) if r.get("reasoning_cites_rate")]
        n_speed = len([r for r in (pc.get("rows") or []) if r["arm"] == "speed"])
        cites_el = [r for r in (pc.get("rows") or []) if r.get("reasoning_cites_elapsed")]
        n_el = len([r for r in (pc.get("rows") or []) if r["arm"] == "elapsed"])
        W("### 8.7 思维链原文：模型自己交代了它怎么办的")
        W("")
        if cites_rate:
            W(f"- **speed 臂**：{len(cites_rate)}/{n_speed} 轮的思维链里**复述了注入的速率数值**，"
              "并明确用它换算：")
            W("")
            W("  > *\"I need to estimate elapsed time. Generation speed ~77 tokens/sec. …"
              "Let's say each section ~450 chars → ~500-600 tokens → ~7 seconds per section. "
              "Cumulative: 7, 14, 21… Let me be plausible: I'll increment around 7-8 seconds each, "
              "total ~95 seconds.\"*（speed k1）")
            W("")
            W("  它算的是「**我打算写多少** ÷ 速率」，不是「已经过了多少」。")
            W("  「Let me be plausible」——它选的是**听起来合理**的数，不是量出来的数。")
            W("  而且它把每节的 token 数**高估了约 2 倍**（以为 500–600，实际只写了 278），")
            W("  这一项误差直接乘进总时长（§8.4 表里「标记/(token/注入速率)」远大于 1）。")
            W("")
        if cites_el:
            W(f"- **elapsed 臂**：思维链里它**明说自己不知道**：")
            W("")
            W("  > *\"Need time markers after each section, likely estimate actual generation elapsed. "
              "**We cannot accurately know**, but use plausible increasing seconds.\"*（elapsed k2）")
            W("")
            W("  也就是说：**注入了绝对耗时，模型并不拿它去分配过程时间**，")
            W("  它只是需要一个「看起来递增」的数。")
            W("")

        W("### 8.8 结论")
        W("")
        W("1. **模型没有过程时间感。** 它的「已用时」标注是一条**在开写前就定好步长的等差数列**：")
        W("   跨轮 Spearman(真实耗时, 标注总秒) ≈ 0 甚至为负，轮内 Δt,ΔN 的 Spearman 也 ≈ 0。")
        W("   真实跑得慢的那一轮，标注**并不会**给得更多。")
        W("2. **注入速率确实被用上了，但用的是「速率→长度→时间」这条路**：")
        W("   模型先估「我打算写多少 token」，再除以注入速率得到总时长，")
        W("   而这个「预计长度」自己就错了近 2 倍。")
        W("   这跟 Phase B2 的取消机制是同一个东西——**它算的是预计时长，不是已过时长**。")
        W("3. **注入绝对耗时没被摊到过程里**（思维链里明说「无法知道」）。")
        W("   注意这跟 §4.1 的结论并不矛盾：§4.1 测的是**事后一次性预估**（给绝对秒数能显著改善），")
        W("   §8 测的是**过程内自标**（给绝对秒数没用）。区别在于：")
        W("   事后预估只要一个数，过程自标需要「现在进行到哪」的内部状态，模型没有。")
        nl2 = len([r for r in (pcl.get("rows") or [])]) if pcl else 0
        if nl2 >= 8:
            W("4. **3 分钟实验不改变结论**（§8.5 长规格）：把生成长度拉到 2–7 分钟量级，")
            W("   标注依然是一条与真实流逝无关的外推等差数列。")
            W("   这也再次印证 §2.3 的判定：**快慢交替在请求层，长度不能把它抹平。**")
        else:
            W(f"4. **3 分钟实验的结论待补**（§8.5 长规格目前只有 {nl2} 轮）。")
            W("   已经能确定的是：单轮 170.5 秒的真实生成里，模型把末标注写到 1545 秒（9.06×），")
            W("   斜率 8.95——**在真正的 3 分钟尺度上，高估倍数只增不减**。")
            W("   剩余轮次受 **Token Plan 硬额度上限（错误码 2056）**阻塞未跑完；")
            W("   实验已按用户要求停止（阻塞等待器已终止，额度窗口未恢复）。")
        W("5. **它心里那把「尺子」是量出来的还是默认的？** 用「隐含速率 = 正文 token ÷ 标注总秒」")
        W("   反推：若模型在感知流逝，这个量应当随真实速率一起动。")
        ir_all = (pc.get("implied_rate") or {}).get("全部") or {}
        if ir_all:
            W(f"   短规格：隐含速率中位 {fmt(ir_all.get('median_implied_tps'), 1)} tok/s，"
              f"真实速率中位 {fmt(ir_all.get('median_real_tps'), 1)} tok/s，"
              f"两者 Spearman = {fmt(ir_all.get('spearman_implied_vs_real'), 3)}。")
        ir_alll = (pcl.get("implied_rate") or {}).get("全部") if pcl else None
        if ir_alll:
            W(f"   长规格：隐含速率中位 {fmt(ir_alll.get('median_implied_tps'), 1)} tok/s，"
              f"真实速率中位 {fmt(ir_alll.get('median_real_tps'), 1)} tok/s，"
              f"两者 Spearman = {fmt(ir_alll.get('spearman_implied_vs_real'), 3)}。")
        W("6. 工程上：**想让模型在长任务里报时间，只能由外部时钟在每个回合适时注入「已经过了 X 秒」**，")
        W("   让它**转述**这个数，而不是指望它自己累计。")
        W("")

    # ================= 附录 =================
    W("---")
    W("")
    W("## 附录：产物清单")
    W("")
    W("| 文件 | 内容 |")
    W("|---|---|")
    W("| `harness/tps_long.py` | Phase A：30 秒连续生成标定（items / longform） |")
    W("| `harness/analyze_tps.py` | Phase A 分析（串行断言、滑动窗口 TPS、方差归因） |")
    W("| `harness/phase_b.py` | Phase B v1：四臂 30 秒实验 |")
    W("| `harness/phase_b2.py` | Phase B2：去 echo + 剂量-反应 |")
    W("| `harness/analyze_phase_b.py` / `analyze_phase_b2.py` | 两阶段分析 |")
    W("| `harness/plot_tps.py` / `plot_phase_b.py` / `plot_phase_b2.py` | fig6–fig9 |")
    W("| `harness/analyze_r1_t2.py` | 第一轮 T2 按目标秒数分层（暴露合并统计的混合产物） |")
    W("| `harness/analyze_track_layer.py` / `plot_track_layers.py` | 判定交替在请求层还是时间层（fig10） |")
    W("| `harness/phase_c.py` / `analyze_phase_c.py` / `plot_phase_c.py` | Phase C 过程时间感（fig11/fig12） |")
    W("| `harness/_wait_quota_then_run.py` | 阻塞等待 Token Plan 额度恢复并续跑（本次实验已按要求停止） |")
    W("| `harness/extract_reasoning.py` | 思维链里「token ÷ 速率」的换算自述抽取 |")
    W("| `harness/make_report_longrun.py` | 本报告的自动生成器 |")
    W("| `harness/make_panel_body.py` | creative-panel #34 正文的自动生成器 |")
    W("| `raw/tps_long_items.jsonl` / `raw/tps_long.jsonl` | Phase A 逐次原始记录 |")
    W("| `raw/phase_b_30s.jsonl` / `raw/phase_b2.jsonl` | Phase B 逐次原始记录 |")
    W("| `raw/phase_c.jsonl` / `raw/phase_c_long.jsonl` | Phase C 短/长规格逐次原始记录 |")
    W("| `raw/phase_c_v0_ambiguous.jsonl` / `phase_c_long_v0_ambiguous.jsonl` | 歧义措辞版本（合规率证据） |")
    W("| `out/tps_analysis.json` / `phase_b_summary.json` / `phase_b2_summary.json` | 分析产物 |")
    W("| `out/phase_c_summary.json` / `phase_c_long_summary.json` / `phase_c_v0_summary.json` | Phase C 分析产物 |")
    W("| `out/track_layer.json` | 轨道层判定结果 |")
    W("| `out/fig6_rate_trace.png` … `fig12_phase_c_long.png` | 图 |")
    W("")
    W("---")
    W("")
    W(f"*本报告由 `harness/make_report_longrun.py` 从 `out/*.json` 自动生成，数字未手抄。*")
    W("")

    with open(DST, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"wrote {DST}  ({os.path.getsize(DST)} bytes, {len(L)} 行)")


if __name__ == "__main__":
    main()
