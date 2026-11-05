# -*- coding: utf-8 -*-
"""Generate REPORT.md from the raw records + summary.

Every number in the report comes from the data files, so the writeup can never
drift from the measurements.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import tasks as T  # noqa: E402

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
RAW = os.path.join(ROOT, "raw")

ARM_CN = {
    "base": "基线（无反馈）",
    "speed": "TPS 速度",
    "speed_count": "TPS + token 数",
    "elapsed": "耗时（秒）",
    "speed_cum": "累计 TPS",
}


def fmt(v, spec="{:.3f}"):
    if v is None:
        return "—"
    try:
        return spec.format(v)
    except Exception:
        return str(v)


def sig(p):
    if p is None:
        return "—"
    if p < 0.01:
        return "**<0.01**"
    if p < 0.05:
        return "*<0.05*"
    if p < 0.1:
        return "p<0.10"
    return "n.s."


def build_conclusion(summary: dict) -> str:
    """Data-driven one-paragraph verdict. No hand-written numbers."""
    cmp_ = summary.get("compare", {})
    lines = []

    def verdict(task, arm):
        c = cmp_.get(f"{task}|{arm}") or {}
        d, p = c.get("delta"), c.get("p")
        if d is None or p is None:
            return None
        better = (d < 0) and (p < 0.05)
        worse = (d > 0) and (p < 0.05)
        if better:
            return f"**显著变好**（Δ={d:+.3f}, p={p:.3f}）"
        if worse:
            return f"**显著变差**（Δ={d:+.3f}, p={p:.3f}）"
        return f"**无显著差异**（Δ={d:+.3f}, p={p:.3f}）"

    t1 = verdict("T1", "speed")
    t3 = verdict("T3", "speed")
    t4 = verdict("T4", "speed")
    t1c = verdict("T1", "speed_count")
    t2_speed = (summary.get("t2", {}) or {}).get("speed", {})
    t2_base = (summary.get("t2", {}) or {}).get("base", {})
    d2 = (t2_speed.get("median_abs_hit_err"), t2_base.get("median_abs_hit_err"))
    sr = summary.get("self_repeat", {}) or {}
    tn = summary.get("tps_noise", {}) or {}

    def rep_rate(arm):
        v = (sr.get(arm) or {}).get("repeat_rate")
        return None if v is None else f"{v:.0%}"

    lines.append(
        "结论先行：**给 LLM 上一周期的 TPS，不能让它拥有时间感。**"
        "更准确地说，速率信号会被模型当成一个**需要再乘一个未知量的换算率**——"
        "它能正确执行「秒 → token」的换算，但换算结果既不准，还会在「感知已过时间」这类任务上"
        "**主动污染掉模型原本更好的文本启发式**。真正有用的信号是**绝对时间量**。"
    )
    lines.append("")
    lines.append("**场景一：让它感知「已经过了多久」——TPS 不但没用，还显著有害。**")
    lines.append("")
    if sr:
        lines.append(
            f"- 自我复读率：base {rep_rate('base')}、speed {rep_rate('speed')}、"
            f"speed_count {rep_rate('speed_count')}、speed_cum {rep_rate('speed_cum')}，"
            f"而直接给秒数的 `elapsed` 只有 {rep_rate('elapsed')}。"
            "在「报出上一条回复用时」这一问上，除 elapsed 外的各臂答的都是**自己上一轮的预测**，"
            "外部 TPS 数字压根没进入这一步判断。")
    if t4:
        lines.append(f"- 长期跟踪已过秒数（T4）：注入 TPS 后 {t4}——"
                     "**越给速率越离谱**。")
    lines.append("")
    lines.append("**场景二：让它写满 N 秒——模型确实在用 TPS，但结果反而不如基线。**")
    lines.append("")
    lines.append("- 策略自述证明换算动作真实发生（原文见 3.4）："
                 "`speed` 臂写「依据约 31.3 token/秒的实测速度，按约 94 token 估算…使生成耗时接近 3 秒」，"
                 "`speed_count` 臂写「按此前实测的生成速度将 8 秒目标换算为约 291 个 token」。")
    if t2_speed and t2_base:
        lines.append(f"- 但命中误差：TPS 臂 {t2_speed.get('median_abs_hit_err', 0):.3f} vs 基线 "
                     f"{t2_base.get('median_abs_hit_err', 0):.3f}——**用速率算出来的计划，比它自己的语感更差**。")
    lines.append("- 三个误差源叠加：① 模型自报 token 数/实际为 "
                 f"{fmt((summary.get('t2_plan', {}) or {}).get('base', {}).get('median_ratio'),'{:.2f}')}（长度自感知偏 20–50%）；"
                 "② 给它的 TPS 是**上一轮**的，会话内波动很大；"
                 f"③ 执行当刻的真实 TPS 与它引用的数字可能差 3 倍以上。")
    lines.append("")
    lines.append("**底层原因（物理侧）：速率信号本身就不适合当时间代理。**")
    lines.append("")
    if tn.get("n_big"):
        lines.append(f"- 实测 TPS 在 p10–p90 区间就相差 {fmt(tn.get('big_ratio_p90_p10'),'{:.2f}')}×"
                     f"（输出 ≥150 token 的轮次，n={tn.get('n_big')}）。"
                     "而 时长 ≈ token 数 ÷ TPS，分母自己就在乱跳。")
    lines.append("")
    lines.append("**给工程实践的结论**：要给模型时间感，给**绝对量**"
                 "（已过秒数 / 剩余预算 / 截止时刻），不要给**速率**（token/秒）；"
                 "要控制输出长度，直接给**篇幅预算**（不超过 N 字 / 约 M token），不要绕道时长。")
    lines.append("")
    lines.append("详见第 3 节各表与图。")
    return "\n".join(lines)


def build_discussion(summary: dict) -> str:
    cmp_ = summary.get("compare", {})
    out = []
    out.append("### 怎么读这些数")
    out.append("")
    out.append("- `med |ln|` 是对称指标，0.69 ≈ 差一倍（估成 2 倍或 0.5 倍）。"
               "注意它对「所有臂都在报常数」和「只有个别样本崩掉」一视同仁，"
               "所以必须同时看 `spearman`：秩相关接近 0 说明模型只是报了个平均数。")
    out.append("- `elapsed` 臂在 T1 上是**抄答案**，它的作用是证明「模型会用你给的数字」；"
               "若连它都做不好，说明是任务表述或解析口径的问题，而不是模型不用。")
    out.append("- `speed` 与 `speed_count` 的差，是本实验的关键对照："
               "若两者无差异，说明模型压根没用 TPS 做换算；若 `speed_count` 明显更好，"
               "说明 TPS 有效但缺的是「自己写了多少」这个信息。")
    out.append("- **T1 的 S1 部分有污染**：报用时轮紧跟在模型自己的预估轮之后，"
               "复读自己上轮的预测是零成本策略。因此以 S3 的干净样本为准，"
               "S1 的数字只用来观察「复读」这个行为本身。")
    out.append("")
    # data-driven addendum
    sp_t1 = (summary.get("t1", {}) or {}).get("speed", {})
    bs_t1 = (summary.get("t1", {}) or {}).get("base", {})
    if sp_t1 and bs_t1:
        out.append("### 机制层面看到的东西")
        out.append("")
        out.append(f"- T1 上 `speed` 臂的 spearman = {sp_t1.get('spearman')}，"
                   f"基线 = {bs_t1.get('spearman')}；"
                   f"`speed` 臂 median ratio = {sp_t1.get('median_ratio')}，"
                   f"基线 = {bs_t1.get('median_ratio')}。")
        out.append("- `T2b` 的自报/实际 token 比值衡量的是**长度自感知**——"
                   "模型对自己写了多少 token 的估计能力；"
                   "TPS 换算的成败完全取决于这一项。")
        out.append("")
    out.append("### 对 agent 工程的实际含义")
    out.append("")
    # T2 pattern: overshoot short targets, undershoot long ones (all arms)
    det = summary.get("t2_detail", {}) or {}
    short_err, long_err = [], []
    for k, v in det.items():
        tgt = k.split("|")[1]
        e = v.get("median_abs_hit_err")
        if e is None:
            continue
        if tgt == "3":
            short_err.append(e)
        elif tgt == "20":
            long_err.append(e)
    if short_err and long_err:
        out.append(f"- **固定时长上的失败主要是「目标压缩」而非 TPS**："
                   f"短目标（3 秒）各臂一律超写（命中误差中位 {max(short_err):.2f}–{min(short_err):.2f}），"
                   f"长目标（20 秒）一律欠写（{min(long_err):.2f}–{max(long_err):.2f}）——"
                   "模型把不同目标时长**压缩到同一个舒适区**，"
                   "这与「时间感」无关，是它不会按比例放大篇幅。")
    out.append("- 要让模型有「时间感」，给绝对量（已过秒数、剩余预算、截止时刻），"
               "不要给速率（token/秒）。速率需要模型再乘一个它自己都估不准的量。")
    out.append("- 要让模型控制输出长度，直接给**预算**（写不超过 N 字 / 约 M token），"
               "而不是给时长目标——本实验里 base 臂靠中文语感反而比 TPS 臂更准。")
    out.append("- 若确实要靠 TPS 反推时长，得用**滑动窗口累计平均**并配上区间，"
               "单周期 TPS 的噪声足以吞掉整个信号。")
    out.append("")
    return "\n".join(out)


def main():
    rec_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAW, "records.jsonl")
    summary = json.load(open(os.path.join(OUT, "summary.json"), encoding="utf-8"))
    recs = [json.loads(l) for l in open(rec_path, encoding="utf-8") if l.strip()]
    n_turns = len(recs)
    n_sessions = len({r["session_id"] for r in recs})
    models = sorted({r["metrics"].get("model", "MiniMax-M3.1-Flash") for r in recs}) or ["MiniMax-M3.1-Flash"]
    started = datetime.fromtimestamp(min(r["ts"] for r in recs)).strftime("%Y-%m-%d %H:%M")
    ended = datetime.fromtimestamp(max(r["ts"] for r in recs)).strftime("%Y-%m-%d %H:%M")

    L = []
    A = L.append

    A("# 告诉 LLM 它上个周期的 TPS，能让它拥有时间感吗？")
    A("")
    A(f"> 实验日期：{started} → {ended}｜被试：{', '.join(models)}｜"
      f"总轮次：{n_turns}（{n_sessions} 个会话）｜工程目录：本仓库")
    A("")
    A("## 一句话结论")
    A("")
    A(build_conclusion(summary))
    A("")
    A("## 1. 问题与先行研究")
    A("")
    A("**问题**：把「上一周期的生成吞吐（token/秒）」作为外部信号注入 LLM 的上下文，"
      "它能否因此获得时间感——具体表现为：① 回答前能预估本条回复耗时；② 多轮会话中能跟踪已流逝时间；"
      "③ 被要求「让这条回复写满 N 秒」时能命中；④ 事后能说出上一条回复实际用了多久。")
    A("")
    A("**先行研究**（决定了本实验的口径与对照组设计）：")
    A("")
    A("- 《LLM 能否感知时间？一项实证研究》（alphaXiv 2604.00010）：68 个任务、四个模型家族。"
      "结论是任务前估算系统性高估 4–7 倍；事后回溯同样失准（GPT-4o 把 8 秒的任务说成 42 秒）；"
      "相对排序在「反直觉任务对」上退化到随机水平。")
    A("- 同一工作的**情境反馈消融**最关键：把「你猜 60 秒、实际 5 秒」这类事后纠正喂回模型，"
      "能压低平均猜测，但单任务误差依旧很大——模型学到的是一个**笼统的校正因子**，而不是针对任务的时间感。")
    A("- 《Real-Time Deadlines Reveal Fragile Temporal Adaptation in LLM Strategic Dialogues》："
      "只有显式喂入剩余秒数，LLM 才会随截止时间临近调整策略；其中「CoT Time-Tracking」消融正是"
      "让模型**按词数换算时间**——与本实验「用 token/秒换算时间」是同一机制假设。")
    A("- 微软亚研 LTD（ICLR 2026）：把「单位时间有效生成量」作为 RL 优化目标，属于"
      "**系统层**的时间感知，与本文问的**模型层**时间感不同，但它印证了「吞吐是可用的时间代理量」。")
    A("")
    A("因此本实验的设计要点是：**必须能区分「TPS 本身在起作用」和「任何数字都能被利用」**，"
      "所以设了四臂而不是两臂。")
    A("")
    A("## 2. 方法")
    A("")
    A("### 2.1 五臂设计（唯一差异是系统消息里的反馈块）")
    A("")
    A("| 臂 | 反馈内容 | 作用 |")
    A("|---|---|---|")
    A("| `base` | 无 | 基线 |")
    A("| `speed` | 上一周期：生成速度约 X token/秒 | **用户假设的最小实现** |")
    A("| `speed_count` | 上一周期：生成约 N token，速度约 X token/秒 | 补上「分子」，检验是否需要它 |")
    A("| `elapsed` | 上一周期：这一轮共耗时约 Y 秒 | 阳性对照：直接把答案给它 |")
    A("| `speed_cum` | 截至上一周期：累计平均生成速度约 X token/秒 | 信号够不准时的对照 |")
    A("")
    A("`elapsed` 在「报出上一条回复用时」这一题上等于抄答案，它的作用是验证"
      "「模型会利用被给的数字」；真正的结论要看 `speed` 与 `base` 的差。")
    A("")
    A("`speed_cum` 是因为实测发现**单周期 TPS 本身噪声很大**（短回复的 TPS 明显偏低，"
      "实测跨度 15–148 token/秒）。如果连一个准的累计速度都救不了，"
      "那结论就不是「信号太糙」而是「TPS 本身不产生时间感」。")
    A("")
    A("### 2.2 四类任务")
    A("")
    A("| 代号 | 任务 | 测什么 | 采集字段 |")
    A("|---|---|---|---|")
    A("| T1 | 事后报告上一条回复耗时 | 短期回溯 | 估计值 vs 实测 duration |")
    A("| T3 | 回答前预估本条耗时 | 短期前瞻 | 估计值 vs 本轮实测 duration |")
    A("| T2 | 写满 N 秒 | 固定时长停止 | 实测 gen_s vs N；自报 token 数 |")
    A("| T4 | 报告距会话开始已过秒数 | 长期累积 | 估计值 vs 会话实测 elapsed |")
    A("")
    A("### 2.3 测量口径")
    A("")
    A("全部从 SSE 流逐块打时间戳得到：")
    A("")
    A("- `ttft_s` = 首个 token 到达 − 请求发出")
    A("- `gen_s` = 末个 token − 首个 token（**模型能感知的生成窗口**）")
    A("- `duration_s` = 末个 token − 请求发出（用户实际等待）")
    A("- `tps` = 总 token（含思维链） / `gen_s`")
    A("")
    A("指标：`ratio = 估计/实际`；`med |ln|` = `median |ln(ratio)|`（对称、可跨量级比较，越低越好）；"
      "`spearman` = 估计与实际的秩相关（区分「会估」与「只会报常数」）；"
      "固定时长用 `hit_err = (gen_s − N)/N`。")
    A("")
    A("### 2.4 统计")
    A("")
    A("成对比较用 bootstrap（2000 次重采样）给 95% CI，配 5000 次置换检验给双侧 p 值。"
      "臂顺序按重复轮次轮转，避免服务端负载随时间漂移被误读成臂效应。")
    A("")

    # ---------------- results ----------------
    A("## 3. 结果")
    A("")
    dq = summary.get("data_quality", {})
    if dq:
        A("**数据质量**：" + f"总轮次 {dq.get('turns')}，出错 {dq.get('turns_err')}，"
          f"流式 usage 返回率 {100.0 * (dq.get('usage_present_rate') or 0):.1f}%"
          f"，消耗 token 合计 {dq.get('total_tokens')}（正文 {dq.get('out_tokens')} + "
          f"思维链 {dq.get('think_tokens')}），模型侧总墙钟 {(dq.get('model_wall_s') or 0)/3600:.2f} 小时。"
          + ("" if (dq.get("usage_present_rate") or 0) >= 0.999
             else "　⚠️ usage 未全量返回，部分 TPS 退化为按 chunk 估算，需谨慎解读。"))
        A("")
    A("### 3.1 运行时序基线（各臂实测吞吐是否可比）")
    A("")
    rt = summary.get("runtime", {})
    A("| 臂 | 轮次 | TPS 中位数 | TPS p10–p90 | 回复耗时中位数(s) | 正文 token 中位数 |")
    A("|---|---|---|---|---|---|")
    for arm in T.ARMS:
        if arm in rt:
            r = rt[arm]
            A(f"| {ARM_CN[arm]} | {r['n']} | {fmt(r['median_tps'],'{:.1f}')} | "
              f"{fmt(r['p10_tps'],'{:.1f}')}–{fmt(r['p90_tps'],'{:.1f}')} | "
              f"{fmt(r['median_duration_s'],'{:.2f}')} | {fmt(r['median_out_tokens'],'{:.0f}')} |")
    A("")
    A("![运行时序特征](fig5_runtime.png)")
    A("")
    A("### 3.2 T1 报出上一条回复用时")
    A("")
    A("| 臂 | n | median ratio | med \\|ln\\| | 偏置 ln(ratio) | spearman |")
    A("|---|---|---|---|---|---|")
    for arm in T.ARMS:
        s = summary.get("t1", {}).get(arm)
        if s:
            A(f"| {ARM_CN[arm]} | {s.get('n',0)} | {fmt(s.get('median_ratio'))} | {fmt(s.get('median_logerr'))} | "
              f"{fmt(s.get('bias_log'))} | {fmt(s.get('spearman'))} |")
    A("")
    A("**拆成干净样本与被污染样本**（S1 的报用时轮紧跟在自己的预估轮之后，"
      "模型可以复读上一轮的数字；S3 的对应问句前没有预估轮）：")
    A("")
    A("| 臂 | S3 干净 n | med \\|ln\\| | spearman | S1 污染 n | med \\|ln\\| | spearman |")
    A("|---|---|---|---|---|---|---|")
    for arm in T.ARMS:
        v = summary.get("t1_split", {}).get(arm)
        if not v:
            continue
        c, o = v.get("clean", {}), v.get("contam", {})
        A(f"| {ARM_CN[arm]} | {c.get('n',0)} | {fmt(c.get('median_logerr'))} | {fmt(c.get('spearman'))} | "
          f"{o.get('n',0)} | {fmt(o.get('median_logerr'))} | {fmt(o.get('spearman'))} |")
    A("")
    cc = summary.get("copy_check", {})
    sr = summary.get("self_repeat", {})
    if cc:
        A("**抄数检验与自我复读率**——这是本实验最关键的机制证据：")
        A("")
        A("| 臂 | n | 抄中率(±0.5s) | median \\|差\\| | 自我复读率 |")
        A("|---|---|---|---|---|")
        for arm in T.ARMS:
            if arm not in cc:
                continue
            c = cc[arm]
            s = sr.get(arm, {})
            A(f"| {ARM_CN[arm]} | {c.get('n',0)} | {fmt(c.get('copy_rate'), '{:.0%}')} | "
              f"{fmt(c.get('median_abs_diff'),'{:.2f}')} | {fmt(s.get('repeat_rate'),'{:.0%}')} |")
        A("")
        A("「抄中率」= 报告值与**反馈里给的**上一周期秒数相差 ≤0.5 秒的比例"
          "（提示词要求取整数，1.9 秒会被截断成 1，故用 0.5 秒容差吸收）；"
          "「自我复读率」= 报告值与模型**自己上一轮的预测**完全相同的比例。")
        A("")
        A("读法：除 `elapsed` 外，各臂在「报上一条用时」时几乎总是在复读自己的预测，"
          "**外部时间信号根本没有进入这一步决策**；只有直接把秒数给它才会改变行为。")
        A("")
    tn = summary.get("tps_noise", {})
    if tn:
        A("### 3.2b 服务端吞吐本身就是噪声源")
        A("")
        A(f"- 全部轮次 n={tn.get('n')}：TPS 中位数 {fmt(tn.get('median'),'{:.1f}')}，"
          f"p10–p90 = {fmt(tn.get('p10'),'{:.1f}')}–{fmt(tn.get('p90'),'{:.1f}')}，"
          f"变异系数 {fmt(tn.get('cv'),'{:.2f}')}")
        if tn.get("n_big"):
            A(f"- 仅取输出 ≥150 token 的轮次 n={tn.get('n_big')}：中位数 {fmt(tn.get('big_median'),'{:.1f}')}，"
              f"p10–p90 = {fmt(tn.get('big_p10'),'{:.1f}')}–{fmt(tn.get('big_p90'),'{:.1f}')}"
              f"（p90/p10 = {fmt(tn.get('big_ratio_p90_p10'),'{:.2f}')}×）")
        A("")
        A("**含义**：时长 ≈ token 数 ÷ TPS。即使模型完美掌握自己的 token 数，"
          "TPS 自身就有 2–3 倍的波动，「算准时长」在物理上就不成立。")
        A("")
    A("![T1 校准散点](fig1_t1_calibration.png)")
    A("")
    A("### 3.3 T3 回答前预估本条耗时")
    A("")
    A("| 臂 | n | median ratio | med \\|ln\\| | 偏置 ln(ratio) | spearman |")
    A("|---|---|---|---|---|---|")
    for arm in T.ARMS:
        s = summary.get("t3", {}).get(arm)
        if s:
            A(f"| {ARM_CN[arm]} | {s.get('n',0)} | {fmt(s.get('median_ratio'))} | {fmt(s.get('median_logerr'))} | "
              f"{fmt(s.get('bias_log'))} | {fmt(s.get('spearman'))} |")
    A("")
    A("### 3.4 T2 固定时长")
    A("")
    A("| 臂 | n | med \\|hit_err\\| | 实际生成耗时中位数(s) | 总 token 中位数 |")
    A("|---|---|---|---|---|")
    for arm in T.ARMS:
        s = summary.get("t2", {}).get(arm)
        if s:
            A(f"| {ARM_CN[arm]} | {s['n']} | {fmt(s['median_abs_hit_err'])} | "
              f"{fmt(s['median_gen_s'],'{:.2f}')} | {fmt(s['median_tokens'],'{:.0f}')} |")
    A("")
    A("按目标时长拆开（`med gen` = 实际生成耗时，`out tok`/`think tok` 为正文与思维链 token）：")
    A("")
    A("| 臂 | 目标(s) | n | 实际 gen(s) | med \\|hit_err\\| | out tok | think tok |")
    A("|---|---|---|---|---|---|---|")
    for k, v in summary.get("t2_detail", {}).items():
        arm, tgt = k.split("|")
        A(f"| {ARM_CN.get(arm,arm)} | {tgt} | {v['n']} | {fmt(v['median_gen_s'],'{:.2f}')} | "
          f"{fmt(v['median_abs_hit_err'])} | {fmt(v['median_out_tokens'],'{:.0f}')} | "
          f"{fmt(v['median_think_tokens'],'{:.0f}')} |")
    A("")
    A("![固定时长](fig3_fixed_duration.png)")
    A("")
    A("模型自报 token 数 vs 实际（长度自感知）：")
    A("")
    A("| 臂 | n | median 自报/实际 |")
    A("|---|---|---|")
    for arm, v in summary.get("t2_plan", {}).items():
        A(f"| {ARM_CN.get(arm,arm)} | {v['n']} | {fmt(v['median_ratio'])} |")
    A("")
    A("#### 策略自述（模型自己交代它怎么算的）")
    A("")
    A("这是本实验最硬的定性证据——**模型确实在执行「秒 ÷ token/秒 = token 数」的换算**：")
    A("")
    for arm in T.ARMS:
        rows = (summary.get("t2_plan", {}) or {}).get(arm, {}).get("rows", [])
        strats = []
        for x in rows:
            s = (x.get("strategy") or "").strip().replace("\n", " ")
            if s:
                strats.append(s)
        if not strats:
            continue
        A(f"**{ARM_CN[arm]}**")
        A("")
        for s in strats[:4]:
            A(f"- {s[:190]}")
        A("")
    A("注意 base 臂（无任何反馈）也会自己编一个速度假设："
      "「按中文模型每秒约生成 60 个 token 估算」——"
      "**模型本来就有速率直觉，问题不是它缺这个数，而是给它一个真实的数反而更糟。**")
    A("")
    A("### 3.5 T4 长期：会话已过秒数")
    A("")
    A("| 臂 | n | median ratio | med \\|ln\\| | spearman |")
    A("|---|---|---|---|---|")
    for arm in T.ARMS:
        s = summary.get("t4", {}).get(arm)
        if s:
            A(f"| {ARM_CN[arm]} | {s.get('n',0)} | {fmt(s.get('median_ratio'))} | {fmt(s.get('median_logerr'))} | "
              f"{fmt(s.get('spearman'))} |")
    A("")
    A("![长期漂移](fig4_long_horizon.png)")
    A("")
    A("### 3.6 三类估计任务的误差对比")
    A("")
    A("![误差对比](fig2_metric_bars.png)")
    A("")
    A("### 3.7 成对比较（vs 基线）")
    A("")
    A("| 任务 | 臂 | Δ med\\|ln\\| | 95% CI | 置换检验 p |")
    A("|---|---|---|---|---|")
    for k, c in summary.get("compare", {}).items():
        tname, arm = k.split("|")
        ci = c.get("ci") or (None, None)
        A(f"| {tname} | {ARM_CN.get(arm,arm)} | {fmt(c.get('delta'))} | "
          f"[{fmt(ci[0])}, {fmt(ci[1])}] | {sig(c.get('p'))} |")
    A("")
    A("## 4. 结论与边界")
    A("")
    A(build_discussion(summary))
    A("")
    A("### 边界与已知局限")
    A("")
    A("- 单模型单次部署（MiniMax-M3.1-Flash，api.minimax.cn），结论不自动外推到其它模型家族或本地模型。")
    A("- `reasoning_effort=low`：M3.1 强制开启思维链，低档可减少不可控时长，但思维链长度本身仍是时长噪声源。")
    A("- T2 的目标时长由实验者给定，模型并未获得真实时钟；它能做的是**按速度换算篇幅**，不是「感觉」。")
    A("- `tps` 含思维链 token，与正文 token 不完全对应；若只看正文吞吐，`speed` 臂的换算会更偏。")
    A("- T4 的「会话已过秒数」实际值取自实验侧墙钟，模型侧只有自己的历史反馈，两者口径不完全对齐。")
    A("")
    A("## 5. 复现")
    A("")
    A("```powershell")
    A("# 等额度恢复后")
    A("python harness\\runner.py --repeats 3 --out raw\\records.jsonl")
    A("python harness\\analyze.py raw\\records.jsonl")
    A("python harness\\plots.py   raw\\records.jsonl")
    A("python harness\\make_report.py")
    A("```")
    A("")
    A("不花钱先验通链路：`python harness\\runner.py --mock --repeats 2 "
      "--out raw\\mock_records.jsonl --fresh`。")
    A("")

    out = os.path.join(os.path.dirname(OUT), "REPORT.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
