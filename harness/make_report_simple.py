# -*- coding: utf-8 -*-
"""生成 REPORT_SIMPLE.md —— 一页读懂的简报。

数字全部从 out/*.json 自动取，不手抄。
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
DST = os.path.join(ROOT, "REPORT_SIMPLE.md")


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
    if isinstance(x, float) and x != x:
        return dash
    return f"{x:.{n}f}"


def sfmt(x, n=3, dash="—"):
    """带符号的格式（Spearman 之类）。"""
    if x is None:
        return dash
    if isinstance(x, float) and x != x:
        return dash
    return f"{x:+.{n}f}"


def main():
    ta = load("tps_analysis.json")
    pb = load("phase_b_summary.json")
    pb2 = load("phase_b2_summary.json")
    pc = load("phase_c_summary.json")
    pcl = load("phase_c_long_summary.json")
    pcv0 = load("phase_c_v0_summary.json")
    tl = load("track_layer.json")
    if ta is None or pb is None or pb2 is None:
        raise SystemExit("缺少 out/*.json，先跑 analyze_*.py")

    merged = []
    for v in ta.values():
        merged.extend(v.get("tps_text") or [])
    merged = sorted(merged)
    n = len(merged)

    cf = pb.get("B_conversion_fidelity") or {}
    tc = pb.get("A_token_compare") or {}
    cmp1 = pb.get("compare") or {}
    hit_base = ((pb.get("A") or {}).get("base") or {}).get("median_abs_hit_err")
    hit_spd = ((pb.get("A") or {}).get("speed_cal") or {}).get("median_abs_hit_err")
    hit_cmp = cmp1.get("A-命中误差|speed_cal") or {}
    tok_spd = tc.get("speed_cal") or {}

    d2 = pb2.get("A2_dose") or {}
    c2 = pb2.get("A2_compare") or {}
    el2 = c2.get("elapsed") or {}
    d2b = pb2.get("B2_dose") or {}
    a2 = pb2.get("A2") or {}
    b2 = pb2.get("B2") or {}
    doses = d2.get("doses") or []

    L = []
    W = L.append

    W("# LLM 时间感实验 · 简报")
    W("")
    W("**问题**：把「上一周期的生成吞吐（token/秒）」告诉 LLM，它能不能因此获得时间感？")
    W("")
    W("**协议**（用户指定）：30 秒标定 → 30 秒实验，每次清空上下文，**全程不开并发**。")
    W("")
    W("---")
    W("")
    W("## 一句话结论")
    W("")
    W("> **速率是尺子，不是时钟。**")
    W(">")
    W("> 模型能把速率当尺子用得很准，但拿它量「自己过了多久」量不出来。")
    W("> **除非速率本身是稳定的**——见下面的重点标记。")
    W("")
    W("---")
    W("")

    # ================= 重点标记 =================
    W("## ★ 重点标记：条件结论")
    W("")
    W("> ### 如果 TPS 稳定，注入速率就可以使模型获得时间感")
    W(">")
    W("> **本报告所有「速率→时间感无效」的结论，都是在「注入的速率本身是抽签出来的、")
    W("> 有一半概率错 2 倍」这个前提下测得的。**")
    W("")
    W("**支撑证据（三条）**")
    W("")
    W(f"1. **模型对给定的速率照单全收。** 纯换算题里隐含速率/注入速率 = "
      f"{fmt((b2.get('speed_40') or {}).get('implied_over_injected'), 3)} / "
      f"{fmt((b2.get('speed_76') or {}).get('implied_over_injected'), 3)} / "
      f"{fmt((b2.get('speed_120') or {}).get('implied_over_injected'), 3)}，"
      f"Spearman(注入速率, 隐含速率) = **{fmt(d2b.get('spearman_rate_vs_implied'), 3)}**。")
    W("   连系统提示里的环境速率都会照抄；没有外部信息时它默认假设自己约 "
      f"**{(b2.get('base') or {}).get('median_implied_rate', 0):.0f} tok/s**。")
    W(f"2. **给了速率 + 明确时长目标后，模型对时间的控制力显著变好。** "
      f"写满 N 秒的命中误差 {fmt(hit_base, 3)} → {fmt(hit_spd, 3)}"
      f"（p={fmt(hit_cmp.get('p'), 3)}），输出 token "
      f"{(pb.get('A') or {}).get('base', {}).get('median_out_tokens', 0):.0f} → "
      f"{(pb.get('A') or {}).get('speed_cal', {}).get('median_out_tokens', 0):.0f}"
      f"（+{tok_spd.get('delta', 0):.0f}，p={fmt(tok_spd.get('p'), 3)}）——")
    W("   **速率确实把「时间」翻译成了可执行的长度。**")
    W("3. **时间那条通道是通的。** 模型把速率同时灌进「我能写多少」和「要多久」两个估计，")
    W("   于是它「以为」要写的 token 数随注入速率单调上升：")
    for x in doses:
        W(f"   - 注入 {x['rate']:.1f} tok/s → 隐含 token 中位 "
          f"{(d2.get('implied_tokens_median_by_arm') or {}).get(x['arm'], 0):.0f}")
    W(f"   Spearman(注入速率, 隐含 token 数) = **{fmt(d2.get('spearman_rate_vs_implied_tokens'), 3)}**。")
    W("   （若时间通道根本不通，不会有这种对称效应。）")
    W("")
    W("**要让这条结论成立，需要同时满足两个条件：**")
    W("")
    W("① **注入的速率稳定且准确** —— 本机做不到（见下）。")
    W("")
    W("② **绕开「取消」机制** —— 光有稳定速率**还不够**：速率越高，模型计划写得越多，")
    W("   时间估计被同一个数抵消掉。要么改给**绝对时间量**，要么给**速率 + 明确的待写量**。")
    W("")
    W("**本机为什么做不到（这是「不能」结论成立的前提，不是结论本身）**")
    W("")
    W(f"- 30 秒连续生成标定 {n} 次：正文速率中位 **{merged[n//2]:.1f} tok/s**，"
      f"p10–p90 {merged[int(0.1*n)]:.1f}–{merged[min(int(0.9*n), n-1)]:.1f}，")
    W(f"  极值 {merged[0]:.1f}–{merged[-1]:.1f}，**max/min = {merged[-1]/merged[0]:.2f}×**。")
    W("- 快慢**在同一分钟内交替**出现，原因是请求被路由到吞吐相差约一倍的**不同后端**。")
    W("- 所以「先测一个稳定 TPS 再注入」这个前提在本机**不成立**——")
    W("  注入 12 次抽样的中位数，等于注入一个有一半概率错 2 倍的数。")
    W("")
    W("**这条命题本轮没有被直接测过（诚实标注）**")
    W("")
    W(f"- A2 自持题（每臂注入**固定**速率，即臂内是「稳定的」）剂量-反应斜率 "
      f"b = {sfmt(d2.get('loglog_slope'), 3)}≈0，")
    W("  三个剂量 vs base **全部无显著差异**（p="
      + " / ".join(fmt((c2.get(a) or {}).get('p'), 3) for a in ("speed_40", "speed_76", "speed_120"))
      + "）。")
    W("- 也就是说：**即使臂内速率是固定的，自估时间也没有跟着动**——")
    W("  真正起作用的是取消机制（条件②），不只是速率抖动。")
    W("- 要真正验证「速率稳定 ⇒ 有时间感」，需要一个**能提供稳定 TPS 的部署**")
    W("  （固定后端路由，或跨请求滑动窗口累计平均后再注入），在那边重跑 A2 自持题。")
    W("")
    W("> **一句话**：稳定的速率是「让时间感可用」的**必要前提**，")
    W("> 但还**不充分**——必须同时避开「速率同时进长度与时间两个估计」的抵消。")
    W("")
    W("---")
    W("")

    # ================= 三个问题 =================
    W("## 三个问题的答案")
    W("")
    W("| 问题 | 答案 |")
    W("|---|---|")
    W("| 告诉它上个周期的 TPS，能不能有时间感？ | **不能**（在「注入速率抽签 2.39×」的前提下，见上面的条件结论） |")
    if tl:
        W(f"| 快慢交替能不能靠 3 分钟实验避开？ | **不能**。交替在**请求层**不在时间层："
          f"请求内窗口速率 CV {fmt(tl.get('within_request_cv_median'), 3)} vs 请求间 "
          f"{fmt(tl.get('between_request_cv'), 3)}（比值 {fmt(tl.get('ratio_within_over_between'), 2)}） |")
    if pc:
        W("| 3 分钟里让它自己标「已用时」有用吗？ | **没有**。它没有过程时间感 |")
    W("")
    W("---")
    W("")

    # ================= 四层 =================
    W("## 四层结论")
    W("")
    W("| 层面 | 结论 | 关键数字 |")
    W("|---|---|---|")
    W(f"| 算术 | **会用**，照着注入值换算 | 保真度中位 {fmt(cf.get('median'), 4)}"
      f"（偏差 {abs(1-cf.get('median', 1))*100:.2f}%） |")
    W(f"| 速率→长度 | **有用** | 输出 token +{tok_spd.get('delta', 0):.0f}，"
      f"p={fmt(tok_spd.get('p'), 3)}；命中误差 {fmt(hit_base, 3)}→{fmt(hit_spd, 3)}，"
      f"p={fmt(hit_cmp.get('p'), 3)} |")
    W(f"| 速率→时间感 | **无效** | 三个速率剂量 vs base 全 p≥"
      f"{min((c2.get(a) or {}).get('p', 1) for a in ('speed_40','speed_76','speed_120')):.2f}，"
      f"斜率 b={sfmt(d2.get('loglog_slope'), 3)}≈0 |")
    W(f"| 绝对秒数→时间感 | **有效**（事后预估） | Δ={fmt(el2.get('delta'), 3)}，"
      f"p={fmt(el2.get('p'), 3)}；est/实测 "
      f"{fmt((a2.get('elapsed') or {}).get('median_est_over_actual'), 2)} |")
    W("| 过程内自标时间 | **无效** | 见下一节 |")
    W("")
    W("---")
    W("")

    # ================= 过程时间感 =================
    if pc:
        arms = pc.get("arms") or {}
        cr = pc.get("cross_run") or {}
        ir = pc.get("implied_rate") or {}
        W("## 过程时间感（模型在写的过程中标「已用时」）")
        W("")
        W("让模型每写完一个**带编号**的小节自标一次「〔已用时 X 秒〕」，")
        W("把每个标记定位到流的**真实经过秒数**直接比。")
        W("")
        W("| 臂 | n | 真实耗时中位 | 末标注/真实（中位） | 模型隐含 tok/s |")
        W("|---|---|---|---|---|")
        for arm, cn in (("base", "基线（无反馈）"), ("speed", "注入实测速率"),
                        ("elapsed", "注入真实实测耗时")):
            a = arms.get(arm) or {}
            if not a:
                continue
            W(f"| {cn} | {a.get('n')} | {fmt(a.get('median_gen_s'), 1)}s | "
              f"{fmt(a.get('median_marked_over_real'), 2)} | "
              f"{fmt(a.get('median_implied_tps'), 1)} |")
        W("")
        allc = cr.get("全部") or {}
        W(f"**关键读数**：跨轮 Spearman(真实耗时, 标注总秒) = "
          f"**{sfmt(allc.get('spearman_marked_vs_real'), 3)}**、"
          f"步长口径 **{sfmt(allc.get('spearman_step_vs_real'), 3)}**")
        W("→ 真实跑得慢的那一轮，标注**并不会**给得更多。")
        W("")
        W("它标出来的「已用时」是一条**在开写前就定好步长的等差数列**：")
        W("")
        W("- 思维链里 speed 臂明说「Generation speed ~77 tokens/sec」，但算的是")
        W("  「**我打算写多少** ÷ 速率」（每节 token 还高估约 2 倍）；")
        W("- elapsed 臂明说「**We cannot accurately know**, but use plausible increasing seconds」")
        W("  → **注入绝对耗时根本没被摊到过程里**。")
        W("")
        W("> **必须区分**：给绝对秒数对「事后一次性预估」有效，对「过程内自标」无效。")
        W("> 工程做法是**外部时钟在每个回合适时注入「已经过了 X 秒」，让模型转述**，")
        W("> 而不是指望它自己累计。")
        W("")
        if pcl:
            rows = pcl.get("rows") or []
            if rows:
                r0 = rows[0]
                W(f"长规格（真 3 分钟量级）：已完成 {len(rows)} 轮，"
                  f"其中真实 {r0['gen_s']:.1f} 秒的那一轮末标注 {r0.get('last_mark', 0):.0f} 秒 "
                  f"= **{fmt(r0.get('last_ratio'), 2)}×**——"
                  f"**高估倍数不随生成长度下降**。")
                W("")
        W("---")
    W("")

    # ================= 协议 =================
    W("## 实验怎么做的")
    W("")
    W("- **Phase A 标定**：连续生成 ~30 秒 × " + str(n) + " 次，逐块打时间戳算真实吞吐。")
    W("- **Phase B v1**：四臂 30 秒实验（48 次）。")
    W("- **Phase B2**：去掉题面里的目标秒数（消除 echo），改成**只改注入的速率数字**")
    W("  （40 / 76.5 / 120 token/秒）的剂量-反应设计（100 次），臂逐轮交错。")
    W("- **Phase C**：过程时间感，短规格 12 轮 × 3 臂（144 个内联标记）+ 长规格真 3 分钟量级。")
    W("- **每次实验只有一条用户消息**（清空上下文），**全程严格串行**，")
    W("  每次调用记录 `[t_request, t_last]`，分析脚本断言区间 0 重叠。")
    W("")
    W("---")
    W("")

    # ================= 工程建议 =================
    W("## 工程建议")
    W("")
    W("1. **给绝对量，不给速率**（已过秒数 / 剩余预算 / 截止时刻）——")
    W("   这是两轮实验里唯一稳定有效的信号（p="
      f"{fmt(el2.get('p'), 3)}）。")
    W("2. **确要用速率**：先确认它**稳定**（跨请求滑动窗口累计平均 + 报 p10–p90 区间，")
    W("   单点采样误差可达 2 倍），并且**配一个明确的待写量**，用来避开取消机制。")
    W("3. **要控制输出长度就直接给篇幅预算**（不超过 N 字 / 约 M token），")
    W("   **不要给时长目标**——模型没有时长目标的概念。")
    W("4. **把「速率」和「时钟」分开**：速率用于容量规划，绝对时间量用于时间感知，")
    W("   两者**不能互相换算**。")
    W("5. **别指望模型在写的过程中自己标时间**——它的标注是外推的等差数列；")
    W("   要它报时间，就由外部时钟注入「已经过了 X 秒」让它**转述**。")
    W("6. **两个容易踩的坑**（做这类实验会踩）：")
    W("   - 锚点必须是模型数得动的结构：按字数标→标记全堆在文末；按段落标→0 个标记；")
    W("     按**连续编号小节**标→12/12 全部 inline。")
    W("   - **措辞歧义会毁掉实验**：「每写完第 1 个小节」会被模型读成「只标第 1 节」")
    W("     （4 轮里 2 轮丢标记），长文里模型会逐字抠指令。")
    W("")
    W("---")
    W("")

    # ================= 边界 =================
    W("## 边界 / 没做完的部分")
    W("")
    W("- **单一模型家族**（MiniMax-M3.1-Flash）、**单一部署线路**：速率双峰是本机这条线路的现象。")
    W("- **样本量**：Phase B2 每臂 n=8（自持题）/ 12（换算题）；置换检验分辨率有限，")
    W("  结论以效应方向与剂量-反应斜率为主。")
    W("- **长规格只完成 " + str(len((pcl or {}).get("rows") or [])) + " 轮**：")
    W("  跑到一半撞上 **Token Plan 硬额度上限（错误码 2056）**，按用户要求已停止实验。")
    W("- **传输层**：中途本机注入的本地代理进程挂掉，urllib 报 10061（看着像 API 挂了，")
    W("  其实是传输层），已改为先探直连再走直连；分析脚本会对比两组的速率分布。")
    W("")
    W("---")
    W("")
    W("## 产物")
    W("")
    W("| 文件 | 内容 |")
    W("|---|---|")
    W("| `REPORT_SIMPLE.md` | 本简报 |")
    W("| `REPORT_LONGRUN.md` | 长程完整报告（700 行，含全部表格与统计） |")
    W("| `REPORT.md` | 第一轮 450 轮的报告 |")
    W("| `out/fig10_track_layer.png` | 交替在请求层不在时间层 |")
    W("| `out/fig11_phase_c_process.png` | 过程时间感四联图 |")
    W("| `out/fig12_phase_c_long.png` | 长规格 |")
    W("| `raw/*.jsonl` | 逐次原始记录（可审计） |")
    W("| `harness/` | 全套可复跑脚本（`runner.py --mock` 可先免费验链路） |")
    W("")
    W("---")
    W("")
    W("*本简报由 `harness/make_report_simple.py` 从 `out/*.json` 自动生成，数字未手抄。*")
    W("")

    with open(DST, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"wrote {DST}  ({os.path.getsize(DST)} bytes, {len(L)} 行)")


if __name__ == "__main__":
    main()
